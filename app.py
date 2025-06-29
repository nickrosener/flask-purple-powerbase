"""A Flask application to control a Bluetooth-enabled adjustable bed and GPIO light."""

from __future__ import annotations

import logging
import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from bluepy import btle  # type: ignore[import]
from flask import Flask, jsonify  # type: ignore[import]
from flask_cors import CORS  # type: ignore[import]
from RPi import GPIO  # type: ignore[import]

# Constants
DEVICE_MAC = "F8:68:CE:13:C3:DF"
RPI_LOCAL_IP = "10.0.0.75"
BINDING_IP = "0.0.0.0"  # noqa: S104
DEVICE_UUID = "db801000-f324-29c3-38d1-85c0c2e86885"
MAX_RETRIES = 5
RETRY_DELAY = 5  # in seconds

UUID_DICT = {
    "lower vib": 8,  # db801060-f324-29c3-38d1-85c0c2e86885
    "upper vib": 9,  # db801061-f324-29c3-38d1-85c0c2e86885
    "lower lift": 6,  # db801042-f324-29c3-38d1-85c0c2e86885
    "upper lift": 5,  # db801041-f324-29c3-38d1-85c0c2e86885
    "light": 14,  # db8010A0-f324-29c3-38d1-85c0c2e86885
    "zero g": [
        5,
        6,
    ],  # db801041-f324-29c3-38d1-85c0c2e86885, db801042-f324-29c3-38d1-85c0c2e86885
    "no snore": 5,  # db801041-f324-29c3-38d1-85c0c2e86885
}


class IgnoreFlaskLog(logging.Filter):
    """A logging filter to ignore specific Flask log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter out specific log messages."""
        # Ignore "GET / HTTP/1.1" 200 messages
        return "GET / HTTP/1.1" not in record.getMessage()


# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logfile.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Apply the filter to Flask's Werkzeug logger
logging.getLogger("werkzeug").addFilter(IgnoreFlaskLog())

# Bluetooth devices
BED_DEVICES = {
    "nick": {"mac": "F8:68:CE:13:C3:DF", "dev": None, "service": None},
    "britt": {"mac": "FA:7A:28:73:FF:3F", "dev": None, "service": None},
}

# Create a lock for Bluetooth communication
bluetooth_lock = threading.Lock()


# Function to connect to Bluetooth
def connect_bluetooth(mac_address: str) -> tuple[btle.Peripheral, btle.Service]:
    """Attempt to connect to the Bluetooth device and return device / service objects.

    Returns
    -------
    tuple
        A tuple containing the Bluetooth Peripheral device and its service.

    Raises
    ------
    SystemExit
        If unable to connect to the Bluetooth device after MAX_RETRIES attempts.

    """
    for attempt in range(1, MAX_RETRIES + 1):
        logger.debug("Bluetooth connection attempt %d/%d for %s", attempt, MAX_RETRIES, mac_address)
        try:
            dev = btle.Peripheral(mac_address, "random")
            logger.info("Connected to Bluetooth device: %s", mac_address)
            service = dev.getServiceByUUID(DEVICE_UUID)
        except btle.BTLEException as e:
            logger.warning("Failed to connect to %s. Retrying...: %r", mac_address, e)
            time.sleep(RETRY_DELAY)
        else:
            return dev, service
    logger.error("Unable to connect to Bluetooth device %s after %d attempts.", mac_address, MAX_RETRIES)
    sys.exit(1)

# Initialize both devices on startup
for name, entry in BED_DEVICES.items():
    dev, service = connect_bluetooth(entry["mac"])
    BED_DEVICES[name]["dev"] = dev
    BED_DEVICES[name]["service"] = service

def write_bluetooth_all(
    characteristic_name: str,
    hex_value: str,
    index: int | None = None,
    initial_percentage: int = 0,
    target_percentage: int = 100,
) -> dict[str, bool]:
    """Write to a Bluetooth characteristic for all bed devices.

    Parameters
    ----------
    characteristic_name : str
        The name of the characteristic.
    hex_value : str
        The hex value to write.
    index : int, optional
        Index for characteristics. Defaults to None.
    initial_percentage : int
        Initial position of the bed (0-100). Defaults to 0.
    target_percentage : int
        Target position of the bed (0-100). Defaults to 100.

    Returns
    -------
    dict
        A dictionary with device names as keys and boolean success status as values.

    """
    results = {}
    with ThreadPoolExecutor(max_workers=len(BED_DEVICES)) as executor:
        future_to_device = {
            executor.submit(
                write_bluetooth,
                device_name,
                characteristic_name,
                hex_value,
                index,
                initial_percentage,
                target_percentage,
            ): device_name
            for device_name in BED_DEVICES
        }
        for future in as_completed(future_to_device):
            device_name = future_to_device[future]
            try:
                results[device_name] = future.result()
            except Exception:
                logger.exception("Exception occurred for %s", device_name)
                results[device_name] = False
    return results


def write_bluetooth(  # noqa: PLR0913
    device_name: str,
    characteristic_name: str,
    hex_value: str,
    index: int | None = None,
    initial_percentage: int = 0,
    target_percentage: int = 100,
) -> bool:
    """Write to a Bluetooth characteristic and handle potential issues.

    Parameters
    ----------
    device_name : str
        The name of the bed device (e.g., "nick" or "britt").
    characteristic_name : str
        The name of the characteristic.
    hex_value : str
        The hex value to write.
    index : int, optional
        Index for characteristics. Defaults to None.
    initial_percentage : int
        Initial position of the bed (0-100). Defaults to 0.
    target_percentage : int
        Target position of the bed (0-100). Defaults to 100.

    """
    dev = BED_DEVICES[device_name]["dev"]
    service = BED_DEVICES[device_name]["service"]

    # Calculate estimated time to move the bed
    max_time_to_move = 30  # max time to move bed from 0 to 100%
    estimated_time = abs(target_percentage - initial_percentage) / 100.0 * max_time_to_move

    # Characteristics that require waiting for movement to complete
    movement_characteristics = ["upper lift", "lower lift"]

    with bluetooth_lock:
        for _ in range(MAX_RETRIES):
            try:
                if index is not None:
                    characteristic = service.getCharacteristics()[UUID_DICT[characteristic_name][index]]
                else:
                    characteristic = service.getCharacteristics()[UUID_DICT[characteristic_name]]

                characteristic.write(bytes.fromhex(hex_value))
                logger.info(
                    "[%s] Wrote %s to %s (index: %s)", device_name, hex_value, characteristic_name, index,
                )

                if characteristic_name in movement_characteristics:
                    logger.info(
                        "[%s] Waiting %d seconds for movement...", device_name, math.ceil(estimated_time),
                    )
                    time.sleep(estimated_time)
            except btle.BTLEException as e:
                logger.warning("[%s] Write failed. Reconnecting...: %r", device_name, e)
                dev, service = connect_bluetooth(BED_DEVICES[device_name]["mac"])
                BED_DEVICES[device_name]["dev"] = dev
                BED_DEVICES[device_name]["service"] = service
            except Exception as e:
                logger.exception("[%s] Unexpected error: %r", device_name, e)  # noqa: TRY401
                return False
            else:
                return True
        logger.error("[%s] Write failed after %d attempts", device_name, MAX_RETRIES)
        return False


def read_bluetooth(device_name: str, characteristic_name: str, index: int | None = None) -> int | None:
    """Read a Bluetooth characteristic and handle potential issues."""
    dev = BED_DEVICES[device_name]["dev"]
    service = BED_DEVICES[device_name]["service"]

    with bluetooth_lock:  # Add this line to acquire the lock
        for _ in range(MAX_RETRIES):
            try:
                if index is not None:
                    characteristic = service.getCharacteristics()[UUID_DICT[characteristic_name][index]]
                else:
                    characteristic = service.getCharacteristics()[UUID_DICT[characteristic_name]]

                decval = int.from_bytes(characteristic.read(), byteorder=sys.byteorder)
                logger.info(
                    "Read value %d from %s (index: %s)",
                    decval,
                    characteristic_name,
                    index,
                )
                return decval  # noqa: TRY300
            except btle.BTLEException as e:
                logger.warning(
                    "Failed to read from %s (index: %s): %r",
                    characteristic_name,
                    index,
                    e,
                )
                logger.info("Attempting to reconnect to Bluetooth device...")
                dev, service = connect_bluetooth(BED_DEVICES[device_name]["mac"])
                BED_DEVICES[device_name]["dev"] = dev
                BED_DEVICES[device_name]["service"] = service
            except KeyError:
                logger.exception(
                    "Characteristic %s not found in UUID_DICT",
                    characteristic_name,
                )
                return None
            except IndexError:
                logger.exception("Index %s out of range for %s", index, characteristic_name)
                return None
            except Exception:
                logger.exception("An unexpected error occurred")
                return None

    logger.error("Unable to read from Bluetooth device after %d attempts.", MAX_RETRIES)
    return None


# GPIO setup
GPIO_PIN = 10
GPIO.setmode(GPIO.BCM)
GPIO.setup(GPIO_PIN, GPIO.OUT)

# Flask setup
app = Flask(__name__)
CORS(app)


# Flask routes
@app.route("/")
def hello_world() -> str:
    """Return a simple message indicating the bed controller is running."""
    return "This is my bed controller"


@app.route("/stop")
def set_stop() -> tuple:
    """Stop both the lower and upper vibration motors of the bed.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to stop")

    success1 = write_bluetooth_all("lower vib", "00")
    time.sleep(1)  # Sleep between commands if needed
    success2 = write_bluetooth_all("upper vib", "00")

    if success1 and success2:
        response = {"status": "success", "message": "Stopped successfully"}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to stop"}
    return jsonify(response), 500


@app.route("/flat")
def set_flat() -> tuple:
    """Set both the upper and lower parts of all beds to the flat (0%) position for all devices."""
    logger.info("Received request to set flat")

    read_results: dict[str, dict[str, int | None]] = {}

    # Step 1: Read upper and lower lift concurrently for all devices
    with ThreadPoolExecutor(max_workers=len(BED_DEVICES) * 2) as executor:
        read_futures = {
            (device_name, lift): executor.submit(read_bluetooth, device_name, lift)
            for device_name in BED_DEVICES
            for lift in ["upper lift", "lower lift"]
        }

        for (device_name, lift), future in read_futures.items():
            try:
                result = future.result()
                read_results.setdefault(device_name, {})[lift] = result
            except Exception as e:
                logger.exception("Error reading %s for %s: %s", lift, device_name, e)  # noqa: TRY401
                read_results.setdefault(device_name, {})[lift] = None

    # Step 2: Fail early if any required read failed
    failed_reads = [
        device_name
        for device_name, values in read_results.items()
        if values.get("upper lift") is None or values.get("lower lift") is None
    ]
    if failed_reads:
        response = {
            "status": "error",
            "message": f"Failed to read current position for: {', '.join(failed_reads)}",
        }
        return jsonify(response), 500

    # Step 3: Write both upper and lower lift to 0% concurrently for all devices
    hexval = hex(0)[2:].zfill(2)
    write_results: dict[str, bool] = dict.fromkeys(BED_DEVICES, True)

    with ThreadPoolExecutor(max_workers=len(BED_DEVICES) * 2) as executor:
        write_futures = {
            executor.submit(
                write_bluetooth,
                device_name,
                lift,
                hexval,
                None,
                read_results[device_name][lift],  # initial_percentage
                0,  # target_percentage
            ): (device_name, lift)
            for device_name in BED_DEVICES
            for lift in ["upper lift", "lower lift"]
        }

        for future in as_completed(write_futures):
            device_name, lift = write_futures[future]
            try:
                result = future.result()
                if not result:
                    logger.error("[%s] Failed to set %s to flat", device_name, lift)
                    write_results[device_name] = False
            except Exception as e:
                logger.exception("[%s] Exception setting %s flat: %s", device_name, lift, e)  # noqa: TRY401
                write_results[device_name] = False

    if all(write_results.values()):
        response = {"status": "success", "message": "Flat set successfully for all devices"}
        return jsonify(response), 200

    failed_devices = [name for name, success in write_results.items() if not success]
    response = {
        "status": "partial_error",
        "message": f"Failed to set flat for: {', '.join(failed_devices)}",
    }
    return jsonify(response), 500



@app.route("/zeroG")
def set_zero_g() -> tuple:
    """Set all beds to the zero G position by adjusting upper and lower lifts.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to set zero G")

    read_results: dict[str, dict[str, int | None]] = {}

    # Step 1: Read positions concurrently
    with ThreadPoolExecutor(max_workers=len(BED_DEVICES) * 2) as executor:
        read_futures = {
            (device, lift): executor.submit(read_bluetooth, device, lift)
            for device in BED_DEVICES
            for lift in ["upper lift", "lower lift"]
        }

        for (device, lift), future in read_futures.items():
            try:
                result = future.result()
                read_results.setdefault(device, {})[lift] = result
            except Exception as e:
                logger.exception("Error reading %s for %s: %s", lift, device, e)  # noqa: TRY401
                read_results.setdefault(device, {})[lift] = None

    # Fail fast if any read failed
    failed_devices = [
        device
        for device, vals in read_results.items()
        if vals.get("upper lift") is None or vals.get("lower lift") is None
    ]
    if failed_devices:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Failed to read positions for: {', '.join(failed_devices)}",
                },
            ),
            500,
        )

    # Step 2: Write target positions concurrently
    write_results: dict[str, bool] = dict.fromkeys(BED_DEVICES, True)
    with ThreadPoolExecutor(max_workers=len(BED_DEVICES) * 2) as executor:
        write_futures = {
            executor.submit(
                write_bluetooth,
                device,
                lift,
                hexval,
                None,
                read_results[device][lift],
                0,
            ): (device, lift)
            for device in BED_DEVICES
            for lift, hexval in [("upper lift", "46"), ("lower lift", "1f")]
        }

        for future in as_completed(write_futures):
            device, lift = write_futures[future]
            try:
                result = future.result()
                if not result:
                    logger.error("[%s] Failed to set %s to zero G", device, lift)
                    write_results[device] = False
            except Exception as e:
                logger.exception("[%s] Exception setting %s: %s", device, lift, e)  # noqa: TRY401
                write_results[device] = False

    if all(write_results.values()):
        return jsonify({"status": "success", "message": "Zero G set successfully"}), 200

    failed = [d for d, ok in write_results.items() if not ok]
    return (
        jsonify(
            {
                "status": "partial_error",
                "message": f"Failed to set zero G for: {', '.join(failed)}",
            },
        ),
        500,
    )


@app.route("/noSnore")
def no_snore() -> tuple:
    """Set the bed to the no snore position (11% upper lift).

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to set no snore (11%)")

    # Step 1: Read current upper height concurrently
    read_results: dict[str, int | None] = {}
    with ThreadPoolExecutor(max_workers=len(BED_DEVICES)) as executor:
        read_futures = {
            device_name: executor.submit(read_bluetooth, device_name, "upper lift")
            for device_name in BED_DEVICES
        }
        for device_name, future in read_futures.items():
            try:
                result = future.result()
                read_results[device_name] = result
            except Exception as e:
                logger.exception("Error reading upper lift for %s: %s", device_name, e)
                read_results[device_name] = None

    # Step 2: Fail early if any reads failed
    failed_devices = [name for name, val in read_results.items() if val is None]
    if failed_devices:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Failed to read upper height for: {', '.join(failed_devices)}",
                }
            ),
            500,
        )

    # Step 3: Write no snore position concurrently
    target_percentage = 11
    hexval = hex(target_percentage)[2:].zfill(2)
    write_results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=len(BED_DEVICES)) as executor:
        write_futures = {
            executor.submit(
                write_bluetooth,
                device_name,
                "upper lift",
                hexval,
                None,
                read_results[device_name],
                target_percentage,
            ): device_name
            for device_name in BED_DEVICES
        }
        for future in as_completed(write_futures):
            device_name = write_futures[future]
            try:
                result = future.result()
                write_results[device_name] = result
            except Exception as e:
                logger.exception("Error writing no snore for %s: %s", device_name, e)
                write_results[device_name] = False

    if all(write_results.values()):
        response = {"status": "success", "message": "No snore set successfully"}
        return jsonify(response), 200

    failed = [d for d, ok in write_results.items() if not ok]
    response = {
        "status": "partial_error",
        "message": f"Failed to set no snore for: {', '.join(failed)}",
    }
    return jsonify(response), 500


@app.route("/moveUpper/<percentage>")
def move_upper(percentage: str) -> tuple:
    """Move the upper part of all beds to the specified percentage position asynchronously.

    Parameters
    ----------
    percentage : str
        The target position as a percentage (0-100).

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to move upper with percentage: %s", percentage)

    try:
        percentage_int = int(percentage)
        if not (0 <= percentage_int <= 100):  # noqa: PLR2004
            msg = "Percentage out of range"
            raise ValueError(msg)  # noqa: TRY301
    except ValueError as e:
        logger.exception("Invalid percentage input: %s. Error: %r", percentage, e)  # noqa: TRY401
        response = {
            "status": "error",
            "message": f"Invalid percentage input: {percentage}",
        }
        return jsonify(response), 400

    hexval = hex(percentage_int)[2:].zfill(2)

    results = {}
    with ThreadPoolExecutor(max_workers=len(BED_DEVICES)) as executor:
        future_to_device = {}
        for device_name in BED_DEVICES:
            initial_percentage = read_bluetooth(device_name, "upper lift")
            if initial_percentage is None:
                logger.warning("Could not read initial percentage for %s", device_name)
                results[device_name] = False
                continue
            future = executor.submit(
                write_bluetooth,
                device_name,
                "upper lift",
                hexval,
                None,
                initial_percentage,
                percentage_int,
            )
            future_to_device[future] = device_name

        for future in as_completed(future_to_device):
            device_name = future_to_device[future]
            try:
                results[device_name] = future.result()
            except Exception:
                logger.exception("Exception occurred for %s", device_name)
                results[device_name] = False

    if all(results.values()):
        response = {
            "status": "success",
            "message": f"Moved upper to {percentage}% for all devices",
        }
        return jsonify(response), 200

    failed_devices = [k for k, v in results.items() if not v]
    response = {
        "status": "partial_error",
        "message": f"Failed to move upper for: {', '.join(failed_devices)}",
    }
    return jsonify(response), 500


@app.route("/getUpperHeight")
def get_upper_height() -> tuple:
    """Return the current upper height of the bed as a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to get upper height")

    # Only check the height of the "nick" bed side
    decval = read_bluetooth("nick", "upper lift")

    if decval is not None:
        response = {"status": "success", "upper_height": decval}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to get upper height"}
    return jsonify(response), 500


@app.route("/moveLower/<percentage>")
def move_lower(percentage: str) -> tuple:
    """Move the lower part of all beds to the specified percentage position asynchronously.

    Parameters
    ----------
    percentage : str
        The target position as a percentage (0-100).

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to move lower with percentage: %s", percentage)

    try:
        percentage_int = int(percentage)
        if not (0 <= percentage_int <= 100):  # noqa: PLR2004
            msg = "Percentage out of range"
            raise ValueError(msg)  # noqa: TRY301
    except ValueError as e:
        logger.exception("Invalid percentage input: %s. Error: %r", percentage, e)
        response = {
            "status": "error",
            "message": f"Invalid percentage input: {percentage}",
        }
        return jsonify(response), 400

    hexval = hex(percentage_int)[2:].zfill(2)

    results = {}
    with ThreadPoolExecutor(max_workers=len(BED_DEVICES)) as executor:
        future_to_device = {}
        for device_name in BED_DEVICES:
            initial_percentage = read_bluetooth(device_name, "lower lift")
            if initial_percentage is None:
                logger.warning("Could not read initial percentage for %s", device_name)
                results[device_name] = False
                continue
            future = executor.submit(
                write_bluetooth,
                device_name,
                "lower lift",
                hexval,
                None,
                initial_percentage,
                percentage_int,
            )
            future_to_device[future] = device_name

        for future in as_completed(future_to_device):
            device_name = future_to_device[future]
            try:
                results[device_name] = future.result()
            except Exception:
                logger.exception("Exception occurred for %s", device_name)
                results[device_name] = False

    if all(results.values()):
        response = {
            "status": "success",
            "message": f"Moved lower to {percentage}% for all devices",
        }
        return jsonify(response), 200

    failed_devices = [k for k, v in results.items() if not v]
    response = {
        "status": "partial_error",
        "message": f"Failed to move lower for: {', '.join(failed_devices)}",
    }
    return jsonify(response), 500


@app.route("/getLowerHeight")
def get_lower_height() -> tuple:
    """Return the current lower height of the bed as a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to get lower height")

    decval = read_bluetooth("lower lift")

    if decval is not None:
        response = {"status": "success", "lower_height": decval}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to get lower height"}
    return jsonify(response), 500


@app.route("/setUpperVib/<percentage>")
def set_upper_vib(percentage: str) -> tuple:
    """Set the upper vibration motor to the specified percentage.

    Parameters
    ----------
    percentage : str
        The target vibration intensity as a percentage (0-100).

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to set upper vib with percentage: %s", percentage)

    # Input validation
    try:
        percentage_int = int(percentage)
        if not (0 <= percentage_int <= 100):  # noqa: PLR2004
            msg = "Percentage out of range"
            raise ValueError(msg)  # noqa: TRY301
    except ValueError as e:
        logger.exception("Invalid percentage input: %s. Error: %r", percentage, e)  # noqa: TRY401
        response = {
            "status": "error",
            "message": f"Invalid percentage input: {percentage}",
        }
        return jsonify(response), 400

    # Convert percentage to hex value and write to Bluetooth characteristic
    hexval = hex(percentage_int)[2:].zfill(2)
    success = write_bluetooth_all("upper vib", hexval)

    if success:
        response = {"status": "success", "message": f"Set upper vib to {percentage}%"}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to set upper vib"}
    return jsonify(response), 500


@app.route("/getUpperVib")
def get_upper_vib() -> tuple:
    """Return the current upper vibration value of the bed as a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to get upper vib")

    decval = read_bluetooth("upper vib")

    if decval is not None:
        response = {"status": "success", "upper_vib": decval}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to get upper vib"}
    return jsonify(response), 500


@app.route("/setLowerVib/<percentage>")
def set_lower_vib(percentage: str) -> tuple:
    """Set the lower vibration motor to the specified percentage.

    Parameters
    ----------
    percentage : str
        The target vibration intensity as a percentage (0-100).

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to set lower vib with percentage: %s", percentage)

    # Input validation
    try:
        percentage_int = int(percentage)
        if not (0 <= percentage_int <= 100):  # noqa: PLR2004
            msg = "Percentage out of range"
            raise ValueError(msg)  # noqa: TRY301
    except ValueError as e:
        logger.exception("Invalid percentage input: %s. Error: %s", percentage, e)  # noqa: TRY401
        response = {
            "status": "error",
            "message": f"Invalid percentage input: {percentage}",
        }
        return jsonify(response), 400

    # Convert percentage to hex value and write to Bluetooth characteristic
    hexval = hex(percentage_int)[2:].zfill(2)
    success = write_bluetooth_all("lower vib", hexval)

    if success:
        response = {"status": "success", "message": f"Set lower vib to {percentage}%"}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to set lower vib"}
    return jsonify(response), 500


@app.route("/getLowerVib")
def get_lower_vib() -> tuple:
    """Return the current lower vibration value of the bed as a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to get lower vib")

    decval = read_bluetooth("lower vib")

    if decval is not None:
        response = {"status": "success", "lower_vib": decval}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to get lower vib"}
    return jsonify(response), 500


@app.route("/light/on")
def turn_light_on() -> tuple:
    """Turn the Bluetooth-controlled light on and return a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to turn light on")

    # Hex value "64" to turn light on
    success = write_bluetooth_all("light", "64")

    if success:
        response = {"status": "success", "message": "Light turned on"}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to turn light on"}
    return jsonify(response), 500


@app.route("/light/off")
def turn_light_off() -> tuple:
    """Turn the Bluetooth-controlled light off and return a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to turn light off")

    # Hex value "00" to turn light off
    success = write_bluetooth_all("light", "00")

    if success:
        response = {"status": "success", "message": "Light turned off"}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to turn light off"}
    return jsonify(response), 500


@app.route("/light/status")
def read_light_status() -> tuple:
    """Return the current Bluetooth-controlled light status as a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to get light status")

    decval = read_bluetooth("light")

    if decval is not None:
        # Consider non-zero as "on" and zero as "off"
        light_status = "on" if decval != 0 else "off"
        response = {"status": "success", "light_status": light_status}
        return jsonify(response), 200
    response = {"status": "error", "message": "Failed to get light status"}
    return jsonify(response), 500


@app.route("/GPIOlight/on")
def turn_gpio_light_on() -> tuple:
    """Turn the GPIO-controlled light on and return a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to turn GPIO light on")

    try:
        GPIO.output(GPIO_PIN, GPIO.HIGH)
        response = {"status": "success", "message": "GPIO light turned on"}
        return jsonify(response), 200
    except Exception as e:
        logger.exception("Failed to turn GPIO light on: %s", e)  # noqa: TRY401
        response = {"status": "error", "message": "Failed to turn GPIO light on"}
        return jsonify(response), 500


@app.route("/GPIOlight/off")
def turn_gpio_light_off() -> tuple:
    """Turn the GPIO-controlled light off and return a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to turn GPIO light off")

    try:
        GPIO.output(GPIO_PIN, GPIO.LOW)
        response = {"status": "success", "message": "GPIO light turned off"}
        return jsonify(response), 200
    except Exception:
        logger.exception("Failed to turn GPIO light off")
        response = {"status": "error", "message": "Failed to turn GPIO light off"}
        return jsonify(response), 500


@app.route("/GPIOlight/status")
def read_gpio_light_status() -> tuple:
    """Return the current GPIO-controlled light status as a JSON response.

    Returns
    -------
    tuple
        A tuple containing the Flask JSON response and HTTP status code.

    """
    logger.info("Received request to get GPIO light status")

    try:
        light_status = GPIO.input(GPIO_PIN)
        # Consider "0" as "off" and "1" as "on"
        light_status_str = "off" if light_status == 0 else "on"
        response = {"status": "success", "gpio_light_status": light_status_str}
        return jsonify(response), 200
    except Exception as e:
        logger.exception("Failed to get GPIO light status: %s", e)  # noqa: TRY401
        response = {"status": "error", "message": "Failed to get GPIO light status"}
        return jsonify(response), 500


if __name__ == "__main__":
    try:
        app.run(host=BINDING_IP, port=8000, debug=False)
    except KeyboardInterrupt:
        logger.info("Gracefully shutting down due to manual interruption...")
    except Exception as e:  # noqa: BLE001
        logger.critical("Failed to start the Flask app: %s", e)
    finally:
        GPIO.cleanup()
        # If applicable, consider closing the Bluetooth connection gracefully here
        try:
            for entry in BED_DEVICES.values():
                if entry["dev"] is not None:
                    entry["dev"].disconnect()
            logger.info("Bluetooth devices disconnected successfully.")
        except Exception as e:
            logger.exception("Failed to disconnect Bluetooth device: %s", e)  # noqa: TRY401
