# Dockerfile
# Build stage using Go 1.23
FROM golang:1.23 AS builder
WORKDIR /app
COPY . .
RUN go mod download
RUN go build -o ordrd-group-x .

# Final stage using Ubuntu
FROM ubuntu:latest
WORKDIR /app
COPY --from=builder /app/ordrd-group-x .
EXPOSE 5001
ENTRYPOINT ["./ordrd-group-x"]
