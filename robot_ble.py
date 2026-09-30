"""Связь с роботом Robert RS01 по Bluetooth LE и протокол команд (из приложения Robertt 1.5.4)."""

import asyncio
import sys
import threading

from bleak import BleakClient, BleakScanner

BLE_NAME = "Robert_ble"
BLE_ADDRESS = "CB:4E:FD:15:8D:21"
WRITE_UUID = "0000ffc1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ffc2-0000-1000-8000-00805f9b34fb"

# Коды действий
# Проверено на роботе: 1 — вперёд, 2 — назад (в старой прошивке считалось наоборот)
FORWARD, BACKWARD, LEFT, RIGHT = 1, 2, 3, 4
IDLE = 77  # «стоп» — им же применяются цвет и режим подсветки
COMBO_RANGE = range(1, 94)  # комбинированные движения (77 пропускается)
HAND_RANGE = range(100, 111)  # движения рук
LEG_RANGE = range(200, 236)  # движения ног

LIGHT_ON, LIGHT_OFF = 0, 4


def packet(action, param=8, speed=0, color=2, light=LIGHT_ON):
    """AA AA CC 32 01 | действие ×2, параметр, скорость, цвет, подсветка, 02 02 | 01 01 | 55 55"""
    body = bytes([action & 0xFF, action & 0xFF, param & 0xFF, speed, color, light, 2, 2])
    return b"\xAA\xAA\xCC\x32\x01" + body + b"\x01\x01\x55\x55"


class LinkError(Exception):
    pass


class BleLink:
    """Синхронная обёртка над bleak: свой asyncio-цикл в фоновом потоке."""

    def __init__(self, on_rx, on_disconnect):
        self.on_rx = on_rx
        self.on_disconnect = on_disconnect
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = None

    @property
    def connected(self):
        return self.client is not None and self.client.is_connected

    def _run(self, coro, timeout=30):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _connect(self):
        dev = await BleakScanner.find_device_by_name(BLE_NAME, timeout=15)
        if dev is None and sys.platform == "darwin":
            # macOS прячет MAC-адреса Bluetooth, поэтому робота можно найти только по имени
            raise LinkError(f"{BLE_NAME} не найден — включите робота и разрешите Терминалу доступ к Bluetooth")
        target = dev or BLE_ADDRESS  # без рекламы пробуем подключиться по известному адресу
        self.client = BleakClient(target, disconnected_callback=lambda _: self.on_disconnect())
        try:
            await self.client.connect(timeout=20)
        except Exception as e:
            self.client = None
            raise LinkError(f"{BLE_NAME} не найден — включите робота ({e})") from e
        await self.client.start_notify(NOTIFY_UUID, lambda _, d: self.on_rx(bytes(d)))
        return self.client.address

    def connect(self):
        return self._run(self._connect(), timeout=60)

    def write(self, data):
        if not self.connected:
            raise LinkError("нет соединения")
        try:
            self._run(self.client.write_gatt_char(WRITE_UUID, data, response=False))
        except Exception as e:
            raise LinkError(str(e)) from e

    def write_async(self, data):
        """Отправка без ожидания — чтобы не подвешивать интерфейс."""
        if not self.connected:
            raise LinkError("нет соединения")
        asyncio.run_coroutine_threadsafe(
            self.client.write_gatt_char(WRITE_UUID, data, response=False), self.loop)

    def close(self):
        if self.client:
            try:
                self._run(self.client.disconnect(), timeout=10)
            except Exception:
                pass
            self.client = None
