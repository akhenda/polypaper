# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY packages/api/package*.json ./
RUN npm ci
COPY packages/api/tsconfig.json ./
COPY packages/api/src ./src
RUN npm run build

# Production stage
FROM node:20-alpine AS production
WORKDIR /app
RUN apk add --no-cache wget
COPY packages/api/package*.json ./
RUN npm ci --only=production
COPY --from=builder /app/dist ./dist
COPY packages/api/src/scripts ./src/scripts
ENV NODE_ENV=production
EXPOSE 3001
CMD ["node", "dist/index.js"]
