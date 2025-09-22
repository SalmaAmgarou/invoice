FROM ubuntu:latest
LABEL authors="amgarou"

ENTRYPOINT ["top", "-b"]