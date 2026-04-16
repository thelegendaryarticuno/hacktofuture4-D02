param(
    [string]$BootstrapServers = "localhost:9092",
    [string[]]$Topics = @("pipeline-events", "diagnosis-required"),
    [string]$KafkaContainer = "pipelineiq-kafka"
)

if (Get-Command docker -ErrorAction SilentlyContinue) {
    foreach ($topic in $Topics) {
        docker exec $KafkaContainer /opt/kafka/bin/kafka-topics.sh --bootstrap-server $BootstrapServers --delete --topic $topic
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Failed to delete topic $topic in container $KafkaContainer. It may not exist or deletion may be disabled."
        } else {
            Write-Host "Deleted topic $topic in container $KafkaContainer"
        }
    }

    foreach ($topic in $Topics) {
        docker exec $KafkaContainer /opt/kafka/bin/kafka-topics.sh --bootstrap-server $BootstrapServers --create --if-not-exists --topic $topic --partitions 3 --replication-factor 1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Failed to create topic $topic in container $KafkaContainer."
        } else {
            Write-Host "Ensured topic $topic exists in container $KafkaContainer"
        }
    }

    exit 0
}

$topicTool = Get-Command kafka-topics.bat -ErrorAction SilentlyContinue
if (-not $topicTool) {
    $topicTool = Get-Command kafka-topics.sh -ErrorAction SilentlyContinue
}

if (-not $topicTool) {
    Write-Host "Kafka topic tool not found. Run the equivalent delete commands manually for: $($Topics -join ', ')"
    exit 1
}

foreach ($topic in $Topics) {
    & $topicTool.Source --bootstrap-server $BootstrapServers --delete --topic $topic
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to delete topic $topic. It may not exist or topic deletion may be disabled."
    } else {
        Write-Host "Deleted topic $topic"
    }
}

foreach ($topic in $Topics) {
    & $topicTool.Source --bootstrap-server $BootstrapServers --create --if-not-exists --topic $topic --partitions 3 --replication-factor 1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to create topic $topic."
    } else {
        Write-Host "Ensured topic $topic exists"
    }
}
