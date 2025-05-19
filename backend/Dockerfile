FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and fonts
RUN apt-get update && \
    apt-get install -y \
    fonts-liberation \
    fonts-dejavu \
    fontconfig \
    sed && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Fix quantstats resample issue by directly editing the file
RUN sed -i 's/returns.sum(axis=0)/returns.sum()/g' /usr/local/lib/python3.11/site-packages/quantstats/_plotting/core.py

# Fix quantstats report generation to use StringIO with proper indentation
RUN sed -i '489,490s/with open(output, "w", encoding="utf-8") as f:/if isinstance(output, str):\n        with open(output, "w", encoding="utf-8") as f:/' /usr/local/lib/python3.11/site-packages/quantstats/reports.py && \
    sed -i '490s/f.write(tpl)/        f.write(tpl)/' /usr/local/lib/python3.11/site-packages/quantstats/reports.py && \
    sed -i '491s/f.close()/        f.close()/' /usr/local/lib/python3.11/site-packages/quantstats/reports.py

# Set matplotlib to use a default font
ENV MATPLOTLIBRC=/usr/local/lib/python3.11/site-packages/matplotlib/mpl-data/matplotlibrc
RUN echo "font.family: sans-serif" >> $MATPLOTLIBRC && \
    echo "font.sans-serif: DejaVu Sans, Liberation Sans, Arial" >> $MATPLOTLIBRC

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"] 