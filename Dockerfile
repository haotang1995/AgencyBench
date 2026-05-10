FROM slimerl/slime:latest

# UTF-8 locale so tmux and Neovim draw box-drawing characters correctly
ENV LANG=C.UTF-8

# Dev tooling missing from the slime base. Pre-installed there: curl, less,
# tree, wget, gpg, ssh, gcc, git, uv, wandb, torch, sglang.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
  build-essential \
  ca-certificates \
  gnupg \
  jq \
  ripgrep \
  unzip \
  && rm -rf /var/lib/apt/lists/*

# Node.js 22 via NodeSource — needed for the npm-installed CLIs below
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
  && apt-get install -y -qq --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

# Azure CLI — lets AzureCliCredential() work inside the container when the
# host's ~/.azure is bind-mounted in (see ai-sandbox.sh). Required for TRAPI
# (MSR's OAuth-gated Azure OpenAI gateway, api://trapi/.default).
# Microsoft's apt repo only ships amd64; on arm64 (e.g. M-series Macs, Win-on-ARM
# WSL) fall back to pip per Microsoft's official ARM64 install guidance.
RUN ARCH="$(dpkg --print-architecture)" \
  && if [ "$ARCH" = "amd64" ]; then \
       install -m 0755 -d /etc/apt/keyrings \
       && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
            | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg \
       && chmod a+r /etc/apt/keyrings/microsoft.gpg \
       && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ $(. /etc/os-release && echo $VERSION_CODENAME) main" \
            > /etc/apt/sources.list.d/azure-cli.list \
       && apt-get update -qq \
       && apt-get install -y -qq --no-install-recommends azure-cli \
       && rm -rf /var/lib/apt/lists/*; \
     else \
       pip install --no-cache-dir --break-system-packages azure-cli; \
     fi

# Docker CLI — for sibling-container workflows (--docker-sock / SANDBOX_DOCKER_SOCK=1).
# Installs only docker-ce-cli (no daemon); the host socket is bind-mounted at runtime.
# Docker's apt repo supports both amd64 and arm64.
RUN install -m 0755 -d /etc/apt/keyrings \
  && curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
       | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
  && chmod a+r /etc/apt/keyrings/docker.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
       > /etc/apt/sources.list.d/docker.list \
  && apt-get update -qq \
  && apt-get install -y -qq --no-install-recommends docker-ce-cli \
  && rm -rf /var/lib/apt/lists/*

# Non-root user (uid 1000) for Claude's --dangerously-skip-permissions
RUN if getent passwd 1000 >/dev/null; then \
      usermod -l sandbox -d /home/sandbox -m $(getent passwd 1000 | cut -d: -f1) 2>/dev/null || true; \
    else \
      groupadd -g 1000 sandbox && useradd -m -u 1000 -g sandbox sandbox; \
    fi

RUN npm install -g @google/gemini-cli @openai/codex @github/copilot @gair/sii-cli \
  && npm cache clean --force

# Portable JDK 21 (Temurin) for AgencyBench Backend/scenario2 which
# compiles and runs Java. Apt-installing default-jdk works fine here too,
# but the Adoptium tarball is smaller and is what we use at runtime.
RUN install -d -o 1000 -g 1000 /home/sandbox/tools \
 && curl -fsSL -o /tmp/jdk.tar.gz \
      https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.5%2B11/OpenJDK21U-jdk_x64_linux_hotspot_21.0.5_11.tar.gz \
 && tar -C /home/sandbox/tools -xzf /tmp/jdk.tar.gz \
 && ln -sfn /home/sandbox/tools/jdk-21.0.5+11 /home/sandbox/tools/jdk \
 && chown -R 1000:1000 /home/sandbox/tools \
 && rm /tmp/jdk.tar.gz
ENV JAVA_HOME=/home/sandbox/tools/jdk
ENV PATH=$JAVA_HOME/bin:$PATH

# Claude Code — install via official script to a world-readable prefix so the
# non-root sandbox user can execute it (the default /root prefix is mode 700).
RUN HOME=/opt/claude-cli curl -fsSL https://claude.ai/install.sh | HOME=/opt/claude-cli bash \
  && chmod -R a+rX /opt/claude-cli \
  && ln -sf /opt/claude-cli/.local/bin/claude /usr/local/bin/claude

# Install AgencyBench Python deps into a dedicated venv. The slime base ships
# several apt-managed Python packages (pyparsing, charset_normalizer, ...)
# without pip RECORD files, so a system-pip install of pinned versions either
# errors on `uninstall-no-record-file` or produces Frankenpackages where new
# .py files overlay old .so files. A venv with --system-site-packages keeps
# the slime base's torch/sglang/megatron stack visible while giving pinned
# AgencyBench versions priority on sys.path.
ENV AGENCYBENCH_VENV=/opt/agencybench-venv
RUN python3 -m venv --system-site-packages "$AGENCYBENCH_VENV"
ENV PATH=$AGENCYBENCH_VENV/bin:$PATH

# COPY requirements.txt only (not the whole repo) so this layer stays cached
# across source-only changes; the repo itself lands at /workspace via bind
# mount at runtime.
COPY requirements.txt /tmp/agencybench-requirements.txt
RUN pip install --no-cache-dir -r /tmp/agencybench-requirements.txt \
 && rm /tmp/agencybench-requirements.txt

WORKDIR /workspace
CMD ["bash"]
