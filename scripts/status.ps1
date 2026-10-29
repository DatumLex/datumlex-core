$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$backendRoot=Join-Path $projectRoot 'backend'
$operations=Join-Path $backendRoot 'data\operations'
foreach ($mode in @('collect','process','all')) {
    $statePath=Join-Path $operations "etl-$mode.json"
    if (Test-Path -LiteralPath $statePath) {
        $state=Get-Content -LiteralPath $statePath -Raw -Encoding utf8 | ConvertFrom-Json
        [pscustomobject]@{Modo=$mode;Estado=$state.status;Etapa=$state.phase;Execucao=$state.job_id;DocumentosTJDFT=$state.stored_unique_tjdft;Meta=$state.target;InicioBrasilia=([TimeZoneInfo]::ConvertTime([DateTimeOffset]$state.started_at,[TimeZoneInfo]::FindSystemTimeZoneById('E. South America Standard Time')).ToString('dd/MM/yyyy HH:mm:ss'))} | Format-List
        if ($mode -eq 'process' -and $state.phase -eq 'nlp') {
            $jobLogs=Join-Path $operations ("etl-logs\"+$state.job_id)
            $progress=Get-ChildItem -LiteralPath $jobLogs -Filter '*-nlp.stderr.log' -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
            if ($progress) { Get-Content -LiteralPath $progress.FullName -Tail 2 -Encoding utf8 }
        }
    }
}
$tasks=Get-ScheduledTask -TaskName 'DatumLex-Local-*' -ErrorAction SilentlyContinue | Where-Object {
    @($_.Actions | Where-Object { $_.WorkingDirectory -and [IO.Path]::GetFullPath($_.WorkingDirectory).TrimEnd('\','/') -eq $backendRoot.TrimEnd('\','/') }).Count -gt 0
}
foreach ($task in $tasks) {
    $info=$task | Get-ScheduledTaskInfo
    [pscustomobject]@{Tarefa=$task.TaskName;Estado=$task.State;UltimoResultado=$info.LastTaskResult;ProximaExecucao=$(if ($task.State -ne 'Disabled') { $info.NextRunTime } else { $null })} | Format-List
}
if (-not $tasks) { Write-Host 'Nenhuma tarefa agendada vinculada a esta pasta.' }
