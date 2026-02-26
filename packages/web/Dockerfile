# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
COPY packages/web/package*.json ./packages/web/
RUN npm ci
COPY packages/web ./packages/web
WORKDIR /app/packages/web
RUN npm run build

# Production stage
FROM node:20-alpine AS production
WORKDIR /app
RUN apk add --no-cache wget
COPY --from=builder /app/packages/web/.next/standalone ./packages/web/.next/standalone
COPY --from=builder /app/packages/web/.next/static ./packages/web/.next/static
COPY --from=builder /app/packages/web/public ./packages/web/public
WORKDIR /app/packages/web
ENV NODE_ENV=production
EXPOSE 3000
CMD ["node", ".next/standalone/server.js"]
