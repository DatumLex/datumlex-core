$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$backendRoot=Join-Path $projectRoot 'backend'
$operations=Join-Path $backendRoot 'data\operations'
$preflightLog = Get-ChildItem -LiteralPath (Join-Path $operations 'preflight-logs') -Filter '*.json' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($preflightLog) {
    $preflight = Get-Content -LiteralPath $preflightLog.FullName -Raw -Encoding utf8 | ConvertFrom-Json
    [pscustomobject]@{SetupStatus=$preflight.status;CheckedAt=$preflight.checked_at;
        Reason=$preflight.reason;DiagnosticLog=$preflightLog.FullName} | Format-List
}
$foundRun = $false
foreach ($mode in @('collect','process','all')) {
    $statePath=Join-Path $operations "etl-$mode.json"
    if (Test-Path -LiteralPath $statePath) {
        $foundRun = $true
        $state=Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
        [pscustomobject]@{Mode=$mode;Status=$state.status;Stage=$state.phase;Job=$state.job_id;Sources=($state.sources -join ',');
            TJDFTDocuments=$state.stored_unique_tjdft;Target=$state.target;StartedAt=$state.started_at;
            FinishedAt=$state.finished_at} | Format-List
        foreach ($step in @($state.steps | Where-Object { $_.status -eq 'failed' })) {
            [pscustomobject]@{FailedStage=$step.name;ExitCode=$step.exit_code;ErrorLog=$step.stderr_log} | Format-List
        }
        if ($state.phase -eq 'nlp') {
            $jobLogs=Join-Path $operations ("etl-logs\"+$state.job_id)
            $progress=Get-ChildItem -LiteralPath $jobLogs -Filter '*-nlp.stderr.log' -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
            if ($progress) { Get-Content -LiteralPath $progress.FullName -Tail 2 -Encoding utf8 }
        }
    }
}
if (-not $foundRun) { Write-Host 'This clone has no recorded ETL runs. Start with scripts/run-etl.ps1 -Once.' }
$tasks=@()
if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
    $tasks=Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    @($_.Actions | Where-Object { $_.WorkingDirectory -and [IO.Path]::GetFullPath($_.WorkingDirectory).TrimEnd('\','/') -eq $backendRoot.TrimEnd('\','/') }).Count -gt 0
}
}
foreach ($task in $tasks) {
    $info=$task | Get-ScheduledTaskInfo
    [pscustomobject]@{Task=$task.TaskName;Status=$task.State;LastResult=$info.LastTaskResult;
        NextRun=$(if ($task.State -ne 'Disabled') { $info.NextRunTime } else { $null })} | Format-List
}
if (-not $tasks) { Write-Host 'No scheduled task is associated with this clone.' }
Write-Host "ETL logs are stored in $(Join-Path $operations 'etl-logs')."
