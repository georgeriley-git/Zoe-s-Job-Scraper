# setup_schedule.ps1
# Registers a Windows Task Scheduler job that runs Zoe's Jobs Scraper
# twice a day (8:00 am and 1:00 pm), every day of the week.
#
# Run this ONCE from a normal (non-admin) PowerShell prompt:
#   cd "C:\Users\George Riley\Zoe's-job-tracker"
#   .\setup_schedule.ps1
#
# To remove the task later:
#   Unregister-ScheduledTask -TaskName "ZoesJobsScraper" -Confirm:$false

$TaskName  = "ZoesJobsScraper"
$BatchFile = "C:\Users\George Riley\Zoe's-job-tracker\run_scrape.bat"
$WorkDir   = "C:\Users\George Riley\Zoe's-job-tracker"
$TempXml   = "$env:TEMP\zoes_job_tracker_task.xml"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$xml = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Scrapes climate tech job board portals at 8am and 1pm daily and refreshes dashboard</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-06-02T08:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <WeeksInterval>1</WeeksInterval>
        <DaysOfWeek>
          <Monday />
          <Tuesday />
          <Wednesday />
          <Thursday />
          <Friday />
          <Saturday />
          <Sunday />
        </DaysOfWeek>
      </ScheduleByWeek>
    </CalendarTrigger>
    <CalendarTrigger>
      <StartBoundary>2026-06-02T13:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <WeeksInterval>1</WeeksInterval>
        <DaysOfWeek>
          <Monday />
          <Tuesday />
          <Wednesday />
          <Thursday />
          <Friday />
          <Saturday />
          <Sunday />
        </DaysOfWeek>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT60M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>C:\Users\George Riley\Zoe's-job-tracker\run_scrape.bat</Command>
      <WorkingDirectory>C:\Users\George Riley\Zoe's-job-tracker</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'@

$xml | Out-File -FilePath $TempXml -Encoding Unicode

schtasks.exe /Create /XML "$TempXml" /TN "$TaskName" /F

Remove-Item $TempXml -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Task '$TaskName' registered successfully."
Write-Host ""
Write-Host "Schedule: Daily (Mon-Sun), 08:00 and 13:00 (2 runs per day)"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Verify:    schtasks /Query /TN $TaskName /V /FO LIST"
Write-Host "  Run now:   schtasks /Run /TN $TaskName"
Write-Host "  Remove:    Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host ""
Write-Host "Dashboard: cd into the folder, run 'python -m http.server 8000', then open http://localhost:8000/dashboard.html"
