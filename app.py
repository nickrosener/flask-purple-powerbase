import logging

# Constants
DEVICE_MAC = "D6:74:A7:CD:D8:B6"
RPI_LOCAL_IP = "10.0.0.75"
DEVICE_UUID = "db801000-f324-29c3-38d1-85c0c2e86885"
MAX_RETRIES = 5
RETRY_DELAY = 5  # in seconds

UUID_DICT = {
    "lower vib": 8,  # db801060-f324-29c3-38d1-85c0c2e86885
    "upper vib": 9,  # db801061-f324-29c3-38d1-85c0c2e86885
    "lower lift": 6,  # db801042-f324-29c3-38d1-85c0c2e86885
    "upper lift": 5,  # db801041-f324-29c3-38d1-85c0c2e86885
    "light": 14,  # db8010A0-f324-29c3-38d1-85c0c2e86885
    "zero g": [5, 6],  # db801041-f324-29c3-38d1-85c0c2e86885, db801042-f324-29c3-38d1-85c0c2e86885
    "no snore": 5  # db801041-f324-29c3-38d1-85c0c2e86885
}


class IgnoreFlaskLog(logging.Filter):
    def filter(self, record):
        # Ignore "GET / HTTP/1.1" 200 messages
        return not ("GET / HTTP/1.1" in record.getMessage())


# Logging setup
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("logfile.log"),
                              logging.StreamHandler()])
logger = logging.getLogger(__name__)

# Apply the filter to Flask's Werkzeug logger
logging.getLogger("werkzeug").addFilter(IgnoreFlaskLog())

from flask import Flask
from flask_cors import CORS
from flask import jsonify
from bluepy import btle
import RPi.GPIO as GPIO
import sys
import time
import threading

# Create a lock for Bluetooth communication
bluetooth_lock = threading.Lock()

# Function to connect to Bluetooth
def connect_bluetooth():
    for _ in range(MAX_RETRIES):
        try:
            dev = btle.Peripheral(DEVICE_MAC, "random")
            service = dev.getServiceByUUID(DEVICE_UUID)
            logger.info(f"Connected to Bluetooth device: {DEVICE_MAC}")
            return dev, service
        except btle.BTLEException as e:
            logger.warning(f"Failed to connect to Bluetooth device. Retrying...: {str(e)}")
            time.sleep(RETRY_DELAY)
    logger.error(f"Unable to connect to Bluetooth device after {MAX_RETRIES} attempts.")
    sys.exit(1)


# Attempt to connect to Bluetooth device
dev, service = connect_bluetooth()


def write_bluetooth(characteristic_name, hex_value, index=None):
    """A helper function to write to a Bluetooth characteristic and handle potential issues."""
    global dev, service  # ensure that you are using the global variables

    with bluetooth_lock:  # Add this line to acquire the lock
        for _ in range(MAX_RETRIES):
            try:
                if index is not None:
                    characteristic = service.getCharacteristics()[UUID_DICT[characteristic_name][index]]
                else:
                    characteristic = service.getCharacteristics()[UUID_DICT[characteristic_name]]

                characteristic.write(bytes.fromhex(hex_value))
                logger.info(f"Wrote {hex_value} to {characteristic_name} (index: {index})")
                return True
            except btle.BTLEException as e:
                logger.warning(f"Failed to write {hex_value} to {characteristic_name} (index: {index}): {str(e)}")
                logger.info("Attempting to reconnect to Bluetooth device...")
                dev, service = connect_bluetooth()  # Attempting reconnection
            except KeyError:
                logger.error(f"Characteristic {characteristic_name} not found in UUID_DICT")
                return False
            except IndexError:
                logger.error(f"Index {index} out of range for {characteristic_name}")
                return False
            except Exception as e:
                logger.error(f"An unexpected error occurred: {str(e)}")
                return False

    logger.error(f"Unable to write to Bluetooth device after {MAX_RETRIES} attempts.")
    return False


def read_bluetooth(characteristic_name, index=None):
    """A helper function to read a Bluetooth characteristic and handle potential issues."""
    global dev, service  # Ensure that you are using the global variables

    with bluetooth_lock:  # Add this line to acquire the lock
        for _ in range(MAX_RETRIES):
            try:
                if index is not None:
                    characteristic = service.getCharacteristics()[UUID_DICT[characteristic_name][index]]
                else:
                    characteristic = service.getCharacteristics()[UUID_DICT[characteristic_name]]

                decval = int.from_bytes(characteristic.read(), byteorder=sys.byteorder)
                logger.info(f"Read value {decval} from {characteristic_name} (index: {index})")
                return decval
            except btle.BTLEException as e:
                logger.warning(f"Failed to read from {characteristic_name} (index: {index}): {str(e)}")
                logger.info("Attempting to reconnect to Bluetooth device...")
                dev, service = connect_bluetooth()  # Attempting reconnection
            except KeyError:
                logger.error(f"Characteristic {characteristic_name} not found in UUID_DICT")
                return None
            except IndexError:
                logger.error(f"Index {index} out of range for {characteristic_name}")
                return None
            except Exception as e:
                logger.error(f"An unexpected error occurred: {str(e)}")
                return None

    logger.error(f"Unable to read from Bluetooth device after {MAX_RETRIES} attempts.")
    return None


# GPIO setup
GPIO_PIN = 10
GPIO.setmode(GPIO.BCM)
GPIO.setup(GPIO_PIN, GPIO.OUT)

# Flask setup
app = Flask(__name__)
CORS(app)


# Flask routes
@app.route('/')
def hello_world():
    logger.info("Received request for root endpoint")
    return 'This is my bed controller'


@app.route("/stop")
def set_stop():
    logger.info("Received request to stop")

    success1 = write_bluetooth("lower vib", "00")
    time.sleep(1)  # Sleep between commands if needed
    success2 = write_bluetooth("upper vib", "00")

    if success1 and success2:
        response = {"status": "success", "message": "Stopped successfully"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to stop"}
        return jsonify(response), 500


@app.route("/flat")
def set_flat():
    logger.info("Received request to set flat")

    # First action
    success1 = write_bluetooth("zero g", "00", index=1)
    time.sleep(22)  # Sleep between commands if needed

    # Second action
    success2 = write_bluetooth("zero g", "00", index=0)

    if success1 and success2:
        response = {"status": "success", "message": "Flat set successfully"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to set flat"}
        return jsonify(response), 500


@app.route("/zeroG")
def set_zero_g():
    logger.info("Received request to set zero G")

    # First action
    success1 = write_bluetooth("zero g", "1f", index=1)
    time.sleep(1)  # Sleep between commands if needed

    # Second action
    success2 = write_bluetooth("zero g", "46", index=0)

    if success1 and success2:
        response = {"status": "success", "message": "Zero G set successfully"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to set zero G"}
        return jsonify(response), 500


@app.route("/noSnore")
def no_snore():
    logger.info("Received request to set no snore")

    # Action to set no snore
    success = write_bluetooth("no snore", "0b")

    if success:
        response = {"status": "success", "message": "No snore set successfully"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to set no snore"}
        return jsonify(response), 500


@app.route("/moveUpper/<percentage>")
def move_upper(percentage):
    logger.info(f"Received request to move upper with percentage: {percentage}")

    # Input validation
    try:
        percentage_int = int(percentage)
        if not (0 <= percentage_int <= 100):
            raise ValueError("Percentage out of range")
    except ValueError as e:
        logger.error(f"Invalid percentage input: {percentage}. Error: {str(e)}")
        response = {"status": "error", "message": f"Invalid percentage input: {percentage}"}
        return jsonify(response), 400

    # Convert percentage to hex value and write to Bluetooth characteristic
    hexval = hex(percentage_int)[2:].zfill(2)
    success = write_bluetooth("upper lift", hexval)

    if success:
        response = {"status": "success", "message": f"Moved upper to {percentage}%"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to move upper"}
        return jsonify(response), 500


@app.route("/getUpperHeight")
def get_upper_height():
    logger.info("Received request to get upper height")

    decval = read_bluetooth("upper lift")

    if decval is not None:
        response = {"status": "success", "upper_height": decval}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to get upper height"}
        return jsonify(response), 500


@app.route("/moveLower/<percentage>")
def move_lower(percentage):
    logger.info(f"Received request to move lower with percentage: {percentage}")

    # Input validation
    try:
        percentage_int = int(percentage)
        if not (0 <= percentage_int <= 100):
            raise ValueError("Percentage out of range")
    except ValueError as e:
        logger.error(f"Invalid percentage input: {percentage}. Error: {str(e)}")
        response = {"status": "error", "message": f"Invalid percentage input: {percentage}"}
        return jsonify(response), 400

    # Convert percentage to hex value and write to Bluetooth characteristic
    hexval = hex(percentage_int)[2:].zfill(2)
    success = write_bluetooth("lower lift", hexval)

    if success:
        response = {"status": "success", "message": f"Moved lower to {percentage}%"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to move lower"}
        return jsonify(response), 500


@app.route("/getLowerHeight")
def get_lower_height():
    logger.info("Received request to get lower height")

    decval = read_bluetooth("lower lift")

    if decval is not None:
        response = {"status": "success", "lower_height": decval}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to get lower height"}
        return jsonify(response), 500


@app.route("/setUpperVib/<percentage>")
def set_upper_vib(percentage):
    logger.info(f"Received request to set upper vib with percentage: {percentage}")

    # Input validation
    try:
        percentage_int = int(percentage)
        if not (0 <= percentage_int <= 100):
            raise ValueError("Percentage out of range")
    except ValueError as e:
        logger.error(f"Invalid percentage input: {percentage}. Error: {str(e)}")
        response = {"status": "error", "message": f"Invalid percentage input: {percentage}"}
        return jsonify(response), 400

    # Convert percentage to hex value and write to Bluetooth characteristic
    hexval = hex(percentage_int)[2:].zfill(2)
    success = write_bluetooth("upper vib", hexval)

    if success:
        response = {"status": "success", "message": f"Set upper vib to {percentage}%"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to set upper vib"}
        return jsonify(response), 500


@app.route("/getUpperVib")
def get_upper_vib():
    logger.info("Received request to get upper vib")

    decval = read_bluetooth("upper vib")

    if decval is not None:
        response = {"status": "success", "upper_vib": decval}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to get upper vib"}
        return jsonify(response), 500


@app.route("/setLowerVib/<percentage>")
def set_lower_vib(percentage):
    logger.info(f"Received request to set lower vib with percentage: {percentage}")

    # Input validation
    try:
        percentage_int = int(percentage)
        if not (0 <= percentage_int <= 100):
            raise ValueError("Percentage out of range")
    except ValueError as e:
        logger.error(f"Invalid percentage input: {percentage}. Error: {str(e)}")
        response = {"status": "error", "message": f"Invalid percentage input: {percentage}"}
        return jsonify(response), 400

    # Convert percentage to hex value and write to Bluetooth characteristic
    hexval = hex(percentage_int)[2:].zfill(2)
    success = write_bluetooth("lower vib", hexval)

    if success:
        response = {"status": "success", "message": f"Set lower vib to {percentage}%"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to set lower vib"}
        return jsonify(response), 500


@app.route("/getLowerVib")
def get_lower_vib():
    logger.info("Received request to get lower vib")

    decval = read_bluetooth("lower vib")

    if decval is not None:
        response = {"status": "success", "lower_vib": decval}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to get lower vib"}
        return jsonify(response), 500


@app.route("/light/on")
def turn_light_on():
    logger.info("Received request to turn light on")

    # Hex value "64" to turn light on
    success = write_bluetooth("light", "64")

    if success:
        response = {"status": "success", "message": "Light turned on"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to turn light on"}
        return jsonify(response), 500


@app.route("/light/off")
def turn_light_off():
    logger.info("Received request to turn light off")

    # Hex value "00" to turn light off
    success = write_bluetooth("light", "00")

    if success:
        response = {"status": "success", "message": "Light turned off"}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to turn light off"}
        return jsonify(response), 500


@app.route("/light/status")
def read_light_status():
    logger.info("Received request to get light status")

    decval = read_bluetooth("light")

    if decval is not None:
        # Consider non-zero as "on" and zero as "off"
        light_status = "on" if decval != 0 else "off"
        response = {"status": "success", "light_status": light_status}
        return jsonify(response), 200
    else:
        response = {"status": "error", "message": "Failed to get light status"}
        return jsonify(response), 500


@app.route("/GPIOlight/on")
def turn_gpio_light_on():
    logger.info("Received request to turn GPIO light on")

    try:
        GPIO.output(GPIO_PIN, GPIO.HIGH)
        response = {"status": "success", "message": "GPIO light turned on"}
        return jsonify(response), 200
    except Exception as e:
        logger.error(f"Failed to turn GPIO light on: {str(e)}")
        response = {"status": "error", "message": "Failed to turn GPIO light on"}
        return jsonify(response), 500


@app.route("/GPIOlight/off")
def turn_gpio_light_off():
    logger.info("Received request to turn GPIO light off")

    try:
        GPIO.output(GPIO_PIN, GPIO.LOW)
        response = {"status": "success", "message": "GPIO light turned off"}
        return jsonify(response), 200
    except Exception as e:
        logger.error(f"Failed to turn GPIO light off: {str(e)}")
        response = {"status": "error", "message": "Failed to turn GPIO light off"}
        return jsonify(response), 500


@app.route("/GPIOlight/status")
def read_gpio_light_status():
    logger.info("Received request to get GPIO light status")

    try:
        light_status = GPIO.input(GPIO_PIN)
        # Consider "0" as "off" and "1" as "on"
        light_status_str = "off" if light_status == 0 else "on"
        response = {"status": "success", "gpio_light_status": light_status_str}
        return jsonify(response), 200
    except Exception as e:
        logger.error(f"Failed to get GPIO light status: {str(e)}")
        response = {"status": "error", "message": "Failed to get GPIO light status"}
        return jsonify(response), 500


if __name__ == '__main__':
    try:
        app.run(host=RPI_LOCAL_IP, port=8000, debug=False)
    except KeyboardInterrupt:
        logger.info("Gracefully shutting down due to manual interruption...")
    except Exception as e:
        logger.critical(f"Failed to start the Flask app: {str(e)}")
    finally:
        GPIO.cleanup()
        # If applicable, consider closing the Bluetooth connection gracefully here
        try:
            dev.disconnect()
            logger.info("Bluetooth device disconnected successfully.")
        except Exception as e:
            logger.error(f"Failed to disconnect Bluetooth device: {str(e)}")
