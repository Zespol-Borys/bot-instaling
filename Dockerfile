# Use an official Python runtime as a parent image
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (only chromium since it's used by both bots)
RUN playwright install chromium

# Copy the rest of the application code into the container
COPY . .

# Expose the port the app runs on
EXPOSE 10000

# Run the application using gunicorn
# 0.0.0.0 is necessary for the container to be reachable
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--threads", "4", "server:app"]
