#!/bin/bash

.IGNORE:
.DEFAULT_GOAL := list

list:
	@@echo "---=List=---"


network:
	docker network create db
	docker network create web

up:
	docker-compose -f ./docker-compose/v1/traefik/docker-compose.yml up -d	
	docker-compose -f ./docker-compose/v1/influxdb/docker-compose.yml up -d
	docker-compose -f ./docker-compose/v1/telegraf/docker-compose.yml up -d
	docker-compose -f ./docker-compose/v1/grafana/docker-compose.yml up -d
	docker-compose -f ./docker-compose/v1/portainer/docker-compose.yml up -d


down:
	docker-compose -f ./docker-compose/v1/traefik/docker-compose.yml down -v
	docker-compose -f ./docker-compose/v1/influxdb/docker-compose.yml down -v
	docker-compose -f ./docker-compose/v1/telegraf/docker-compose.yml down -v
	docker-compose -f ./docker-compose/v1/grafana/docker-compose.yml down -v
	docker-compose -f ./docker-compose/v1/portainer/docker-compose.yml down -v


cl:
	docker stop $(docker ps -a -q)
	docker rm $(docker ps -a -q)
	docker system prune -a -f
	# docker network create web
	# docker network create db


## Next add
# docker-compose -f ./docker-compose/v1/netdata/docker-compose.yml up -d
# docker-compose -f ./docker-compose/v1/pihole/docker-compose.yml up -d
# docker-compose -f ./docker-compose/v1/smokeping/docker-compose.yml up -d	
# docker-compose -f ./docker-compose/v1/homeassistant/docker-compose.yml up -d
# docker-compose -f ./docker-compose/v1/postgres/docker-compose.yml up -d
# docker-compose -f ./docker-compose/v1/airflow/docker-compose.yml up -d
# docker-compose -f ./docker-compose/v1/adminer/docker-compose.yml up -d
# docker-compose -f ./docker-compose/v1/eclipse-mosquitto/docker-compose.yml up -d

#Command on Raspberry


#/mnt/mydisk/repo/docker/

repo_url = ""

git_root=/mnt/
git_folder=${git_root}mydisk/repo/
docker_git_folder=${git_folder}docker/

user_name = 646826
user_email = ${user_name}@gmail.com

cl:
	docker stop $(docker ps -a -q)
	docker rm $(docker ps -a -q)
	docker system prune -a -f
	docker network create web
	docker network create db
	sudo chmod 0777 ${git_root} -R
	git --git-dir=${docker_git_folder} pull
	git --git-dir=${docker_git_folder} clean -f -d

init:
	sudo apt update && sudo apt -y dist-upgrade
	sudo apt -y install docker docker-compose
	sudo usermod -aG docker pi
	sudo systemctl enable docker
	sudo systemctl start docker
	sudo apt install git
	git config --global user.name ${user_name}
	git config --global user.email ${user_email}
	git config --global credential.helper cache
	git config --global credential.helper 'cache --timeout=9600'
	sudo mkdir -p ${git_folder}
	sudo chmod 0777 ${git_root} -R
	cd ${git_folder}
	sudo git clone ${repo_url}
	sudo chmod 0777 ${git_root} -R
	sudo shutdown -r now

gt:
	cd
	sudo rm ${git_root} -f -d -r
	sudo mkdir -p ${git_folder}
	sudo chmod 0777 ${git_root} -R
	cd ${git_folder}
	sudo git clone ${repo_url}
	sudo chmod 0777 ${git_root} -R

upd:
	sudo chmod 0777 ${git_root} -R
	cd ${docker_git_folder}
	git reset --hard
	git clean -f -d
	git pull