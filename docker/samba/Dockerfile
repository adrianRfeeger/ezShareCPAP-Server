FROM debian:bookworm-slim
LABEL org.opencontainers.image.source="https://github.com/adrianRfeeger/ezShareCPAP-Server"
RUN apt-get update && apt-get install -y --no-install-recommends samba && rm -rf /var/lib/apt/lists/*
COPY smb.conf /etc/samba/smb.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
