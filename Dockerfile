FROM node:22-alpine AS dashboard-build

WORKDIR /app/dashboard
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard ./
RUN npm run build


FROM python:3.13-slim

WORKDIR /app
COPY . /app
COPY --from=dashboard-build /app/dashboard/dist /app/dashboard/dist

RUN pip install --no-cache-dir -e .

EXPOSE 8787
CMD ["agentmesh", "dashboard", "--host", "0.0.0.0", "--port", "8787"]
