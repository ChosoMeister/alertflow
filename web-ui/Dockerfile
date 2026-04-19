FROM node:20-alpine

WORKDIR /app
RUN apk add --no-cache tzdata
ENV TZ=Asia/Tehran

# Copy package files
COPY package.json ./

# Install dependencies with legacy peer deps
RUN npm install --legacy-peer-deps

# Copy source code
COPY . .

# Set environment variables
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Accept build-time API URL (passed from docker-compose build args)
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Build the application (NEXT_PUBLIC_* vars are baked in at this step)
RUN npm run build

# Expose port
EXPOSE 3000

# Start the application
CMD ["npm", "start"]
