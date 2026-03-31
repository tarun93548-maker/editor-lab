FROM node:20-slim
RUN apt-get update && apt-get install -y chromium fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 xdg-utils ffmpeg && rm -rf /var/lib/apt/lists/*
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV CHROMIUM_PATH=/usr/bin/chromium
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
RUN npx tsc
EXPOSE 3100
CMD ["node", "dist/server.js"]
