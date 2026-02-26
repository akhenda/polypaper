# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY packages/web/package*.json ./
RUN npm ci
COPY packages/web ./
RUN npm run build

# Production stage
FROM node:20-alpine AS production
WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", "server.js"]
