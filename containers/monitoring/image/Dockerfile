FROM ubuntu:22.04
RUN apt-get update
RUN apt install python3-pip -y
RUN DEBIAN_FRONTEND=noninteractive TZ=Europe/Rome apt-get -y install tzdata
RUN apt install python3-h5netcdf bash -y
RUN apt install python3-opencv bash -y
ADD requirements.txt /foliage/
WORKDIR /foliage
RUN pip3 install -r requirements.txt
RUN apt install vim -y
ADD dati_aggiuntivi/* /foliage/dati_aggiuntivi/
ADD app/*.py /foliage/app/
WORKDIR /foliage/app
CMD ["/usr/bin/python3", "app.py"]






