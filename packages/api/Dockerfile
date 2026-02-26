# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
COPY packages/api/package*.json ./packages/api/
RUN npm ci
COPY packages/api/tsconfig.json ./packages/api/
COPY packages/api/src ./packages/api/src
RUN npm run build -w packages/api

# Production stage
FROM node:20-alpine AS production
WORKDIR /app
RUN apk add --no-cache wget
COPY package*.json ./
COPY packages/api/package*.json ./packages/api/
RUN npm ci --only=production -w packages/api
COPY --from=builder /app/packages/api/dist ./packages/api/dist
COPY packages/api/src/scripts ./packages/api/src/scripts
WORKDIR /app/packages/api
ENV NODE_ENV=production
EXPOSE 3001
CMD ["node", "dist/index.js"]
