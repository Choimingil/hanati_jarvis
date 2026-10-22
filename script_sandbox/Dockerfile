FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends bash ca-certificates && rm -rf /var/lib/apt/lists/*
USER 65534:65534
WORKDIR /tmp
ENTRYPOINT []
CMD ["/bin/bash"]
