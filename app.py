from flask import Flask
from flask_cors import CORS
from bluepy import btle
import RPi.GPIO as GPIO
import sys
import time

# TODO: You WILL need to change the mac address below to be the address of your bed's bluetooth module
DEVICE_MAC = "D6:74:A7:CD:D8:B6"
# TODO: You WILL need to change the Local IP address below to be the address of your RPI
RPI_LOCAL_IP = "10.0.0.214"
# You do NOT need to change the below UUID if you have the same bed
DEVICE_UUID = "db801000-f324-29c3-38d1-85c0c2e86885"

UUID_DICT = {
    "lower vib": 8,  # db801060-f324-29c3-38d1-85c0c2e86885
    "upper vib": 9,  # db801061-f324-29c3-38d1-85c0c2e86885
    "lower lift": 6,  # db801042-f324-29c3-38d1-85c0c2e86885
    "upper lift": 5,  # db801041-f324-29c3-38d1-85c0c2e86885
    "light": 14,  # db8010A0-f324-29c3-38d1-85c0c2e86885
    "zero g": [5, 6],  # db801041-f324-29c3-38d1-85c0c2e86885, db801042-f324-29c3-38d1-85c0c2e86885
    "no snore": 5  # db801041-f324-29c3-38d1-85c0c2e86885
}

dev = btle.Peripheral(DEVICE_MAC, "random")
service = dev.getServiceByUUID(DEVICE_UUID)

# TODO: If you are using the GPIO to control your LEDs, you may want to set the pin number, I use 10 on my RPI 0 W
GPIO_PIN = 10
GPIO.setmode(GPIO.BCM)
GPIO.setup(GPIO_PIN, GPIO.OUT)

app = Flask(__name__)
CORS(app)


@app.route('/')
def hello_world():
    return 'This is my bed controller'


@app.route("/stop")
def setStop():
    subService1 = service.getCharacteristics()[UUID_DICT["lower vib"]]
    subService1.write(bytes.fromhex("00"))
    time.sleep(1)
    subService2 = service.getCharacteristics()[UUID_DICT["upper vib"]]
    subService2.write(bytes.fromhex("00"))
    return 'stopped'


@app.route("/flat")
def setFlat():
    subService1 = service.getCharacteristics()[UUID_DICT["zero g"][1]]
    subService1.write(bytes.fromhex("00"))
    time.sleep(22)
    subService2 = service.getCharacteristics()[UUID_DICT["zero g"][0]]
    subService2.write(bytes.fromhex("00"))
    return 'flat'


@app.route("/zeroG")
def setZeroG():
    subService1 = service.getCharacteristics()[UUID_DICT["zero g"][1]]
    subService1.write(bytes.fromhex("1f"))
    time.sleep(1)
    subService2 = service.getCharacteristics()[UUID_DICT["zero g"][0]]
    subService2.write(bytes.fromhex("46"))
    return 'zeroG'


@app.route("/noSnore")
def noSnore():
    subService1 = service.getCharacteristics()[UUID_DICT["no snore"]]
    subService1.write(bytes.fromhex("0b"))
    return 'noSnore'


@app.route("/moveUpper/<percentage>")
def moveUpper(percentage):
    subService1 = service.getCharacteristics()[UUID_DICT["upper lift"]]
    hexval = hex(int(percentage))[2:]
    if len(hexval) == 1:
        hexval = "0" + hexval
    subService1.write(bytes.fromhex(hexval))
    return 'move upper'


@app.route("/getUpperHeight")
def getUpperHeight():
    subService1 = service.getCharacteristics()[UUID_DICT["upper lift"]]
    decval = int.from_bytes(subService1.read(), byteorder=sys.byteorder)
    return str(decval)


@app.route("/moveLower/<percentage>")
def moveLower(percentage):
    subService1 = service.getCharacteristics()[UUID_DICT["lower lift"]]
    hexval = hex(int(percentage))[2:]
    if len(hexval) == 1:
        hexval = "0" + hexval
    subService1.write(bytes.fromhex(hexval))
    return 'move lower'


@app.route("/getLowerHeight")
def getLowerHeight():
    subService1 = service.getCharacteristics()[UUID_DICT["lower lift"]]
    decval = int.from_bytes(subService1.read(), byteorder=sys.byteorder)
    return str(decval)


@app.route("/setUpperVib/<percentage>")
def setUpperVib(percentage):
    subService1 = service.getCharacteristics()[UUID_DICT["upper vib"]]
    hexval = hex(int(percentage))[2:]
    if len(hexval) == 1:
        hexval = "0" + hexval
    subService1.write(bytes.fromhex(hexval))
    return 'setting upper vib'


@app.route("/getUpperVib")
def getUpperVib():
    subService1 = service.getCharacteristics()[UUID_DICT["upper vib"]]
    decval = int.from_bytes(subService1.read(), byteorder=sys.byteorder)
    return str(decval)


@app.route("/setLowerVib/<percentage>")
def setLowerVib(percentage):
    subService1 = service.getCharacteristics()[UUID_DICT["lower vib"]]
    hexval = hex(int(percentage))[2:]
    if len(hexval) == 1:
        hexval = "0" + hexval
    subService1.write(bytes.fromhex(hexval))
    return 'setting lower vib'


@app.route("/getLowerVib")
def getLowerVib():
    subService1 = service.getCharacteristics()[UUID_DICT["lower vib"]]
    decval = int.from_bytes(subService1.read(), byteorder=sys.byteorder)
    return str(decval)


@app.route("/light/on")
def turnLightOn():
    subService = service.getCharacteristics()[UUID_DICT["light"]]
    subService.write(bytes.fromhex("64"))
    return 'on'


@app.route("/light/off")
def turnLightOff():
    subService = service.getCharacteristics()[UUID_DICT["light"]]
    subService.write(bytes.fromhex("00"))
    return 'off'


@app.route("/light/status")
def readLightStatus():
    subService1 = service.getCharacteristics()[UUID_DICT["light"]]
    decval = int.from_bytes(subService1.read(), byteorder=sys.byteorder)
    if (decval == 0):
        return '0'
    else:
        return '1'


@app.route("/GPIOlight/on")
def turnGPIOLightOn():
    GPIO.output(GPIO_PIN, GPIO.HIGH)
    return 'on'


@app.route("/GPIOlight/off")
def turnGPIOLightOff():
    GPIO.output(GPIO_PIN, GPIO.LOW)
    return 'off'


@app.route("/GPIOlight/status")
def readGPIOLightStatus():
    lightStatus = GPIO.input(GPIO_PIN)
    if (lightStatus == 0):
        return '0'
    else:
        return '1'


if __name__ == '__main__':
    app.run(host=RPI_LOCAL_IP, port=8000, debug=False)
