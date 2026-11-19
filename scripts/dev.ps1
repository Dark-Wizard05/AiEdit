# Start AiEdit locally: API + SvelteKit frontend

$Root = Split-Path -Parent $PSScriptRoot

$LoginUrl = 'http://localhost:5173/login'



function Wait-ForUrl {

    param(

        [string]$Url,

        [int]$TimeoutSeconds = 60

    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {

        try {

            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2

            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {

                return $true

            }

        } catch {

            Start-Sleep -Milliseconds 500

        }

    }

    return $false

}



Write-Host "Starting AiEdit backend on http://127.0.0.1:8000 ..."

Start-Process powershell -ArgumentList @(

    '-NoExit',

    '-Command',

    "Set-Location '$Root'; py -m uvicorn backend.api:app --reload --host 127.0.0.1 --port 8000"

) -WindowStyle Normal



Start-Sleep -Seconds 2



Write-Host "Starting AiEdit frontend on http://localhost:5173 ..."

$Frontend = Join-Path $Root 'frontend'

if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) {

    Write-Host "Installing frontend dependencies..."

    Push-Location $Frontend

    npm install

    Pop-Location

}



Start-Process powershell -ArgumentList @(

    '-NoExit',

    '-Command',

    "Set-Location '$Frontend'; npm run dev"

) -WindowStyle Normal



Write-Host ""

Write-Host "Waiting for backend and frontend to be ready ..."



$apiReady = Wait-ForUrl -Url 'http://127.0.0.1:8000/health'

$frontendReady = Wait-ForUrl -Url 'http://localhost:5173/'



if (-not $apiReady) {

    Write-Host "Warning: backend did not respond in time. Check the API PowerShell window."

}

if (-not $frontendReady) {

    Write-Host "Warning: frontend did not respond in time. Check the frontend PowerShell window."

}



if ($apiReady -and $frontendReady) {

    Write-Host "Opening $LoginUrl in your default browser ..."

    Start-Process $LoginUrl

} else {

    Write-Host "Open $LoginUrl manually once both servers are running."

}



Write-Host ""

Write-Host "Keep both PowerShell windows open while you use AiEdit — closing either one stops that server."

Write-Host "You can minimize them; just do not close them until you are done."

Write-Host "If signup fails, restart the API window (auth routes require a fresh backend)."


