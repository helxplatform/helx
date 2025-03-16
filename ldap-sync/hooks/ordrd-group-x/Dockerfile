# Build stage using Go 1.23
FROM golang:1.23 AS builder
WORKDIR /app

# Cache dependencies
COPY go.mod go.sum ./
RUN go mod download

# Copy the source code and build
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -a -o ordrd-group-x .

# Final stage using Ubuntu
FROM ubuntu:latest
WORKDIR /app
COPY --from=builder /app/ordrd-group-x .

# Expose port 8080
EXPOSE 8080

# Run the hook service
CMD ["./ordrd-group-x"]
