$connections = netstat -ano | Select-String ':8000'
foreach ($line in $connections) {
    $parts = ($line.ToString() -split '\s+') | Where-Object { $_ -ne '' }
    if ($parts.Length -ge 5 -and $parts[3] -eq 'LISTENING') {
        Stop-Process -Id ([int]$parts[4]) -ErrorAction SilentlyContinue
    }
}

