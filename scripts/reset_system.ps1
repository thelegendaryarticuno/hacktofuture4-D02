param(
    [string]$BootstrapServers = "localhost:9092"
)

python "${PSScriptRoot}\reset_backend_state.py"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& "${PSScriptRoot}\reset_kafka_topics.ps1" -BootstrapServers $BootstrapServers
