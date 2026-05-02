# Use the official Python 3.9 slim image
FROM python:3.9-slim

# Enable 32-bit architecture and install wine
# This allows us to run the legacy IITPFILE.exe locally on Hugging Face Spaces!
RUN dpkg --add-architecture i386 \
    && apt-get update -y \
    && apt-get install -y --no-install-recommends wine wine32 \
    && rm -rf /var/lib/apt/lists/*

# Set up a new user named "user" with user ID 1000
# (Hugging Face Spaces runs as a non-root user for security)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    WINEPREFIX=/home/user/.wine \
    WINEDEBUG=-all

WORKDIR $HOME/app

# Initialize wine prefix
RUN wine cmd /c echo "Wine initialized"

# Copy the requirements file (from the mep_opt directory)
COPY --chown=user ./mep_opt/requirements.txt $HOME/app/requirements.txt

# Install dependencies
RUN pip install --no-cache-dir --upgrade -r $HOME/app/requirements.txt

# Copy the legacy IIT PAVE software so it's included in the container.
# Use JSON-array COPY form because Dockerfile does not honor shell quotes
# for whitespace in paths.
COPY --chown=user ["IIT Pave - Original/", "/home/user/app/IIT Pave - Original/"]

# Copy the mep_opt backend directory into the container
COPY --chown=user ./mep_opt $HOME/app/mep_opt

# Start the FastAPI application on port 7860
# (Hugging Face Spaces expects web services to run on port 7860)
CMD ["uvicorn", "mep_opt.web.main:app", "--host", "0.0.0.0", "--port", "7860"]
