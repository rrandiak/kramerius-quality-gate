FROM python:3.12.7-slim
WORKDIR /app
COPY server.py page.jpg ./
USER 65534
EXPOSE 8080
CMD ["python", "server.py"]
