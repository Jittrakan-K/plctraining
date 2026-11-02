"""
gx_bridge.py  -  เชื่อม GX Works2 (GX Simulator2) หรือ PLC จริง เข้ากับเว็บ PLC Training Kit Sim

ภาพรวม
    เว็บ (เครื่องจำลอง)  <-- WebSocket ws://localhost:8765 -->  gx_bridge.py  <-- MX Component -->  GX Simulator2 / PLC
    - เว็บส่งสถานะเซนเซอร์/ปุ่ม X0-X7 มาให้ bridge เขียนลง PLC
    - bridge อ่าน Y0-Y7 จาก PLC ส่งกลับไปขยับเครื่องจำลอง

สิ่งที่ต้องมี
    1) GX Works2 + เปิด GX Simulator2 (Debug -> Start/Stop Simulation) ให้อยู่ในโหมด RUN
    2) MX Component (ของ Mitsubishi) ติดตั้งแล้ว และตั้งค่าใน "Communication Setup Utility"
       ให้มี Logical Station Number (เช่น 1) ที่เชื่อมต่อแบบ GX Simulator2
    3) Python บน Windows:  pip install pywin32 websockets
       * MX Component รุ่นเก่า (Ver.4) เป็น COM แบบ 32 บิต ต้องใช้ Python 32 บิต
         ถ้าใช้ MX Component Ver.5 ที่มี ActUtlType64 ใช้ Python 64 บิตได้

วิธีรัน
    python gx_bridge.py --station 1              # GX Simulator2 (เขียนอินพุตลง X0-X7 ได้โดยตรง)
    python gx_bridge.py --station 2 --input M100 # PLC จริง: อินพุตจากเว็บเขียนลง M100-M107 แทน X
    python gx_bridge.py --demo                   # ทดสอบการเชื่อมต่อ ไม่ต้องมี PLC (Y = X)

หมายเหตุ PLC จริง
    X ของ PLC จริงถูกอ่านจากขั้วอินพุตทุกสแกน เขียนทับจากภายนอกไม่ได้
    ให้ใช้ --input M100 แล้วในโปรแกรม Ladder ใช้ M100-M107 แทน X0-X7 (เช่น LD M102 แทน LD X2)
    ระวัง: เครื่องจำลองจะสั่งเอาต์พุตจริงของ PLC ด้วย อย่าต่อกับเครื่องจักรที่มีคนทำงานอยู่
"""
import argparse
import asyncio
import json
import sys
import time

try:
    import websockets
except ImportError:
    sys.exit("ไม่พบโมดูล websockets  ->  pip install websockets")


# ---------------------------------------------------------------- PLC backends
class DemoBackend:
    """ไม่มี PLC: สะท้อน X กลับเป็น Y เพื่อทดสอบว่าเว็บกับ bridge คุยกันได้"""
    name = "demo"

    def __init__(self):
        self.x = [0] * 8

    def open(self):
        return "โหมดทดสอบ (ไม่มี PLC): Y0-Y7 = X0-X7"

    def write_inputs(self, x):
        self.x = list(x)

    def read_outputs(self):
        return list(self.x)

    def close(self):
        pass


class MXBackend:
    """ใช้ MX Component (ActUtlType) คุยกับ GX Simulator2 หรือ PLC ตาม Logical Station Number"""
    name = "mx"
    PROGIDS = ("ActUtlType.ActUtlType", "ActUtlType64.ActUtlType64")

    def __init__(self, station, input_dev):
        self.station = station
        self.input_dev = input_dev.upper()   # "X" หรือ เช่น "M100"
        self.act = None
        self.last_x = None

    def _in_name(self, i):
        if self.input_dev == "X":
            return "X%o" % i                  # X ของ FX เป็นเลขฐาน 8
        letter = self.input_dev.rstrip("0123456789")
        base = int(self.input_dev[len(letter):] or 0)
        return "%s%d" % (letter, base + i)

    @staticmethod
    def _ret(r):
        """win32com คืนค่าเป็น int หรือ tuple (ret, out...) แล้วแต่วิธี dispatch"""
        return r if isinstance(r, tuple) else (r,)

    def open(self):
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            raise RuntimeError("ไม่พบ pywin32  ->  pip install pywin32  (ต้องรันบน Windows)")
        pythoncom.CoInitialize()
        last_err = None
        for pid in self.PROGIDS:
            try:
                try:
                    self.act = win32com.client.gencache.EnsureDispatch(pid)
                except Exception:
                    self.act = win32com.client.Dispatch(pid)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        if self.act is None:
            raise RuntimeError(
                "เปิด MX Component ไม่ได้ (%s)\n"
                "  - ติดตั้ง MX Component แล้วหรือยัง\n"
                "  - MX Component Ver.4 ต้องใช้ Python 32 บิต" % last_err)
        self.act.ActLogicalStationNumber = self.station
        ret = self._ret(self.act.Open())[0]
        if ret != 0:
            raise RuntimeError(
                "Open() ล้มเหลว รหัส 0x%08X\n"
                "  - GX Simulator2 เปิดอยู่และอยู่ในโหมด RUN หรือยัง\n"
                "  - Logical Station %d ตั้งค่าเป็น GX Simulator2 ใน Communication Setup Utility แล้วหรือยัง"
                % (ret & 0xFFFFFFFF, self.station))
        return "เชื่อมต่อ MX Component แล้ว (Logical Station %d, อินพุตเขียนลง %s-%s)" % (
            self.station, self._in_name(0), self._in_name(7))

    def _get(self, dev):
        try:
            r = self._ret(self.act.GetDevice(dev))
        except TypeError:
            r = self._ret(self.act.GetDevice(dev, 0))
        if r[0] != 0:
            raise RuntimeError("GetDevice(%s) รหัส 0x%08X" % (dev, r[0] & 0xFFFFFFFF))
        return int(r[1]) if len(r) > 1 else 0

    def write_inputs(self, x):
        x = [1 if v else 0 for v in x[:8]]
        for i, v in enumerate(x):
            if self.last_x is None or self.last_x[i] != v:
                ret = self._ret(self.act.SetDevice(self._in_name(i), v))[0]
                if ret != 0:
                    raise RuntimeError("SetDevice(%s) รหัส 0x%08X" % (self._in_name(i), ret & 0xFFFFFFFF))
        self.last_x = x

    def read_outputs(self):
        # อ่าน Y0-Y17 เป็น word เดียว (bit0 = Y0) ถ้าไม่ได้ค่อยอ่านทีละบิต
        try:
            try:
                r = self._ret(self.act.ReadDeviceBlock("Y0", 1))
            except TypeError:
                r = self._ret(self.act.ReadDeviceBlock("Y0", 1, 0))
            if r[0] == 0 and len(r) > 1:
                w = r[1][0] if isinstance(r[1], (list, tuple)) else int(r[1])
                return [(w >> i) & 1 for i in range(8)]
        except Exception:  # noqa: BLE001
            pass
        return [self._get("Y%o" % i) for i in range(8)]

    def close(self):
        try:
            if self.act is not None:
                self.act.Close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- WebSocket server
class Bridge:
    def __init__(self, plc, poll_ms):
        self.plc = plc
        self.poll = poll_ms / 1000.0
        self.clients = set()
        self.status = ""
        self.ok = False
        self.x = [0] * 8
        self.y = None

    async def send_all(self, msg):
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send(data)
            except Exception:  # noqa: BLE001
                self.clients.discard(ws)

    async def handler(self, ws, path=None):
        self.clients.add(ws)
        print("[web] เชื่อมต่อแล้ว (%d)" % len(self.clients))
        await ws.send(json.dumps({"type": "status", "ok": self.ok, "msg": self.status}))
        if self.y is not None:
            await ws.send(json.dumps({"type": "outputs", "y": self.y, "run": True}))
        try:
            async for raw in ws:
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                if m.get("type") == "inputs" and isinstance(m.get("x"), list):
                    self.x = [1 if v else 0 for v in m["x"][:8]] + [0] * (8 - len(m["x"][:8]))
        finally:
            self.clients.discard(ws)
            print("[web] ตัดการเชื่อมต่อ (%d)" % len(self.clients))

    async def plc_loop(self):
        last_print = 0
        while True:
            try:
                if not self.ok:
                    self.status = self.plc.open()
                    self.ok = True
                    print("[plc]", self.status)
                    await self.send_all({"type": "status", "ok": True, "msg": self.status})
                self.plc.write_inputs(self.x)
                y = self.plc.read_outputs()
                if y != self.y:
                    self.y = y
                    await self.send_all({"type": "outputs", "y": y, "run": True})
                if time.time() - last_print > 5:
                    print("[plc] X=%s  Y=%s" % ("".join(map(str, self.x)), "".join(map(str, y))))
                    last_print = time.time()
            except Exception as e:  # noqa: BLE001
                if self.ok or self.status != str(e):
                    print("[plc] ผิดพลาด:", e)
                self.ok = False
                self.status = str(e)
                self.plc.close()
                await self.send_all({"type": "status", "ok": False, "msg": self.status.splitlines()[0]})
                await asyncio.sleep(2)
            await asyncio.sleep(self.poll)


async def main():
    ap = argparse.ArgumentParser(description="Bridge: GX Works2 / GX Simulator2 <-> PLC Training Kit Sim")
    ap.add_argument("--station", type=int, default=1, help="MX Component Logical Station Number (ค่าเริ่มต้น 1)")
    ap.add_argument("--input", default="X", help="อุปกรณ์ที่ใช้รับอินพุตจากเว็บ: X (Simulator) หรือ เช่น M100 (PLC จริง)")
    ap.add_argument("--port", type=int, default=8765, help="พอร์ต WebSocket (ค่าเริ่มต้น 8765)")
    ap.add_argument("--poll", type=int, default=30, help="รอบอ่าน/เขียน PLC เป็นมิลลิวินาที (ค่าเริ่มต้น 30)")
    ap.add_argument("--demo", action="store_true", help="ทดสอบโดยไม่ต่อ PLC")
    a = ap.parse_args()

    plc = DemoBackend() if a.demo else MXBackend(a.station, a.input)
    br = Bridge(plc, a.poll)
    async with websockets.serve(br.handler, "localhost", a.port):
        print("Bridge พร้อมที่ ws://localhost:%d  (กด Ctrl+C เพื่อหยุด)" % a.port)
        print("เปิดไฟล์ plc-training-kit-sim.html จากเครื่อง แล้วกด 'เชื่อมต่อ'")
        await br.plc_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nหยุด bridge แล้ว")
