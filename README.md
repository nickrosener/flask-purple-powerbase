# flask-purple-powerbase

This is a Python3 Flask server implementation for a Reverie/Purple Powerbase. This has been created by myself (@jbyerline) 
and you are free to use this code and adapt however you may like. Feel free to fork or put up a PR if you feel so inclined 
and I will review it as time permits.

This Flask API is designed to work with the Homebridge plugin [here](https://github.com/jbyerline/homebridge-purple-powerbase).

The tutorial begins here: 

Please note, this has been tested on a RPI 0W and a RPI 4. The PI needs to have Bluetooth 4.0 Low Energy which to my
knowledge is only available natively on those 2 raspberry PI's 
_________________________________________
## Prerequisite
This guide assumes that you already have the following set up: 

- A Raspberry Pi 0 W (MUST be a W) or a Raspberry Pi 4 with Raspian
- SSH enabled for ease of setup (not required if you're a fan of typing)
- Some knowledge of local networking

## Set Up
### Step 1
Login to your device (locally or over SSH)
```
    ssh myUser@myLocalRpiIp
```
### Step 2
Check for Updates
```
    sudo apt update && sudo apt upgrade
```
### Step 3
Identify your RPI's local IP address
```
    ifconfig
```

Your results will look something like this: 
```
lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
    inet 127.0.0.1  netmask 255.0.0.0
    inet6 ::1  prefixlen 128  scopeid 0x10<host>
    loop  txqueuelen 1000  (Local Loopback)
    RX packets 0  bytes 0 (0.0 B)
    RX errors 0  dropped 0  overruns 0  frame 0
    TX packets 0  bytes 0 (0.0 B)
    TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0

wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
    inet 10.0.0.75  netmask 255.0.0.0  broadcast 10.255.255.255
    inet6 fd5d:bd35:1481:1:9d25:753b:25bf:b050  prefixlen 64  scopeid 0x0<global>
    ether b8:27:eb:6c:be:28  txqueuelen 1000  (Ethernet)
    RX packets 300745  bytes 117984533 (112.5 MiB)
    RX errors 0  dropped 0  overruns 0  frame 0
    TX packets 12035  bytes 1657489 (1.5 MiB)
    TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0
```
The line your looking for will begin with "wlan0:" (assuming you are connected to WiFi and not Ethernet). Under the wlan0
line you will see "inet x.x.x.x". This is your Pi's local IP address. 

### Step 4
Reserve your RPI's local IP address either in software or in your networks router. Look up how to do this for your specific router.

### Step 5
Change directories to home
``` 
    cd
```
Clone this repo:
``` 
    git clone https://github.com/jbyerline/flask-purple-powerbase.git
```
Change directories to flask-purple-powerbase
``` 
    cd flask-purple-powerbase
```

### Step 6
Find your Bed's Bluetooth MAC address. This will be needed for the Raspberry Pi (RPI) to be able to connect to the
bed. 
``` 
   sudo hcitool lescan
```
This will produce a long list of bluetooth devices near you as well as their MAC addresses. Mine was titled
"RevCB_C1". Once you see one with probably a similar name, hit ctrl+c to stop the scan. Write down your MAC 
address exactly as is.

Note: it is important that there are no other bluetooth devices connected to your bed when you do this scan,
IE. the Purple or Reverie apps. Once the app has found your bed. Connect to is and write down the

### Step 7
Edit app.py to include your MAC address and IP address
``` 
   nano app.py
```
Edit the two lines below to be your MAC and IP addresses we noted earlier
``` 
    #TODO: You WILL need to change the mac address below to be the address of your bed's bluetooth module
    DEVICE_MAC = "XX:XX:XX:XX:XX:XX"
    # TODO: You WILL need to change the Local IP address below to be the address of your RPI
    RPI_LOCAL_IP = "X.X.X.X"
```
Hit ctrl+x then y then enter to save

### Step 8
Install python pip3
``` 
   sudo apt-get -y install python3-pip
```
Verify python pip3 installation
``` 
   pip3 --version
```

### Step 9
Install python pip3 required packages (Note: sudo is required for later step)
``` 
   sudo pip3 install flask
```
```
   sudo pip3 install bluepy
```

### Step 10
Start Flask API for fist time (Note: you must be in the flask-purple-powerbase directory)
```
   sudo python3 app.py
```

### Step 11
Test out your API by going to:
```
   http://[yourLocalIP]:8000/moveUpper/50
```
If all goes well, your bed will move up 50%. Make sure no other bluetooth devices are connected to the bed so that 
the RPI can. 

This will send it back to flat:
```
   http://[yourLocalIP]:8000/moveUpper/0
```

### Step 11
Configure autostart of the API on boot:
```
   sudo nano /etc/rc.local
```

insert the line immediately before the exit 0 line
```
   sudo python3 /home/pi/flask-purple-powerbase/app.py &> /home/pi/log.txt 2>&1
```
Hit ctrl+x then y then enter to save

### Step 12
Use your API. 
```
   sudo reboot
```
If all is well then you should be able to use all the API endpoints in this server. They are listed below. Test them
out and create your own web app. Or hook this flask API up to homebridge for control in the home app. Here is the 
repo for that: [Purple Powerbase Homebridge](https://github.com/jbyerline/homebridge-purple-powerbase)


## Configuration Params
|             Endpoint          |                         Description                        |  Method  |
| ----------------------------- | ---------------------------------------------------------- |:--------:|
| `/`                           | default webpage for api                                    |    get   |
| `/stop`                       | turn off massagers                                         |    get   |
| `/flat`                       | make bed flat (top then bottom)                            |    get   |
| `/zeroG`                      | set bed to ZeroG mode                                      |    get   |
| `/noSnore`                    | set bed to No Snore mode                                   |    get   |
| `/moveUpper/<percentage>`     | move top of bed to int percentage (ie. moveUpper/50)       |    get   |
| `/getUpperHeight`             | get current height of top of bed                           |    get   |
| `/moveLower/<percentage>`     | move bottom of bed to int percentage (ie. moveUpper/50)    |    get   |
| `/getLowerHeight`             | get current height of bottom of bed                        |    get   |
| `/setUpperVib/<percentage>`   | set upper massager to int percentage (ie. setUpperVib/50)  |    get   |
| `/getUpperVib`                | get current strength of upper massager                     |    get   |
| `/setLowerVib/<percentage>`   | set lower massager to int percentage (ie. setUpperVib/50)  |    get   |
| `/getLowerVib`                | get current strength of lower massager                     |    get   |
| `/light/on`                   | turn nightlight on (via bluetooth)                         |    get   |
| `/light/off`                  | turn nightlight off (via bluetooth)                        |    get   |
| `/light/status`               | get nightlight status (via bluetooth)                      |    get   |
| `/GPIOlight/on`               | turn nightlight on (via GPIO Relay Pin 10)                 |    get   |
| `/GPIOlight/off`              | turn nightlight off (via GPIO Relay Pin 10)                |    get   |
| `/GPIOlight/status`           | get nightlight status (via GPIO Relay Pin 10)              |    get   |

## Hint
- Your base URL is: "http://X.X.X.X:8000", where the X's is the local IP of your RPI.
