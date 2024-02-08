#
# Dockerfile to help test builds on linux while developing locally
#
FROM ubuntu:latest

# Avoid prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    curl \
    make \
    python3.11 \
    python3.11-venv \
    build-essential \
    vim \
    && rm -rf /var/lib/apt/lists/* # clean up

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Install Node.js using NVM
ENV NVM_DIR="/root/.nvm"
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install 18 \
    && nvm use 18 \
    && nvm alias default 18 \
    # Ensure node and npm are available for subsequent commands in the Docker build process
    && ln -s "$NVM_DIR/versions/node/$(nvm current)/bin/node" /usr/bin/node \
    && ln -s "$NVM_DIR/versions/node/$(nvm current)/bin/npm" /usr/bin/npm

# Adjust PATH to include the Cargo bin directory for Rust and local Poetry binaries
ENV PATH="/root/.local/bin:/root/.cargo/bin:$PATH"

# Verify installations
RUN rustc --version \
    && node --version \
    && npm --version

# Copy the application files
COPY filzl filzl
COPY pyproject.toml .
COPY Cargo.toml .
COPY Cargo.lock .
COPY src src
COPY create_filzl_app create_filzl_app
COPY README.md .
COPY Makefile .

# RUN make install-deps