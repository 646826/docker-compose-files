# Docker Compose Files  
All applications are configured to work through Traefik.   
Added authorization for services that do not use their own authorization.

# Docker-compose files that are committed

| [Traefik](https://github.com/traefik/traefik)  | [InfluxDB 2](https://www.influxdata.com/products/influxdb/) | [Grafana](https://grafana.com/) 
| ------------- | ------------- | ------------- |
| **Local URL:** http://traefik.localhost/ | **Local URL:** http://influxdb.localhost/  | **Local URL:** http://grafana.localhost/ |
| **Login:** admin  | **Login:** admin | **Login:** admin |
| **Password:** bc183SEgTbuNqxLyuGTd2s | **Password:** bc183SEgTbuNqxLyuGTd2s | **Password:** bc183SEgTbuNqxLyuGTd2s |
| **Checked on version:** Traefik 2.4.13  | **Checked on version:** InfluxDB 2.0.7   | **Checked on version:** Grafana v8.1.1 |  

| [Portainer](https://www.portainer.io/) | [Telegraf](https://www.influxdata.com/time-series-platform/telegraf/) |
| ------------- | ------------- |
| **Local URL:** http://portainer.localhost/ | - |
| **Login:** admin | - |
| **Password:** bc183SEgTbuNqxLyuGTd2s | - |
|  **Checked on version:** Portainer 2.6.2 | **Checked on version:** Telegraf 1.19.2 |

# Docker-compose files that are will do

- [ ] openhab
- [ ] eclipse-mosquitto
- [ ] netdata
- [ ] k3s

# To start  

## Use make command
> ```make network``` - will create network DB and WEB  
> ```make up```  - will create all containers  
> ```make down``` - will remove all containers  

![image](https://user-images.githubusercontent.com/1565611/129490254-a7cdd3c1-9e2c-4635-8146-ebb12b284107.png)

## Local configs  

### Traefik
> **Local URL:** http://traefik.localhost/  
> **Login:** admin  
> **Password:** bc183SEgTbuNqxLyuGTd2s  
> **Checked on version:** Traefik 2.4.13  

![image](https://user-images.githubusercontent.com/1565611/129490399-28e75cce-00eb-403d-8823-f6b1124077cc.png)


### InfluxDB 2
> **Local URL:** http://influxdb.localhost/  
> **Login:** admin  
> **Password:** bc183SEgTbuNqxLyuGTd2s  
> **Checked on version:** InfluxDB 2.0.7  

![image](https://user-images.githubusercontent.com/1565611/129490919-58244757-6ca0-4504-9303-f314bef7b061.png)


### Grafana
> **Local URL:** http://grafana.localhost/  
> **Login:** admin  
> **Password:** bc183SEgTbuNqxLyuGTd2s  
> **Dashboards:** http://grafana.localhost/dashboards  
> **Checked on version:** Grafana v8.1.1  

![image](https://user-images.githubusercontent.com/1565611/129490333-4dd37b31-d8f6-42ba-a61e-0cf66b92082a.png)


### Telegraf
> .  
> **Checked on version:** Telegraf 1.19.2  

### Portainer
> **Local URL:** http://portainer.localhost/   
> **Login:** admin   
> **Password:** bc183SEgTbuNqxLyuGTd2s   
> **Checked on version:** Portainer 2.6.2 

![image](https://user-images.githubusercontent.com/1565611/129490439-1a02111a-2c6b-424b-a535-353e833fb860.png)


# Install more tools for VSCODE

## Make 
> **Go to:** https://sourceforge.net/projects/ezwinports/files/   
> **Download:** make-4.3-without-guile-w32-bin.zip  
> Extract zip  
> Copy the contents to your C:\Program Files\Git\mingw64 merging the folders, but do NOT overwrite/replace any existing files.  
