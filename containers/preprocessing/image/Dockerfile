FROM ghcr.io/osgeo/gdal
RUN apt-get update
RUN apt install -y python3-pip
WORKDIR /foliage
COPY ./requirements.txt /foliage/requirements.txt 
RUN pip install --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org --no-cache-dir -r /foliage/requirements.txt --break-system-packages
COPY . /foliage/app
CMD ["uvicorn", "app.scripts.service:app", "--host", "0.0.0.0", "--port","8000"]
