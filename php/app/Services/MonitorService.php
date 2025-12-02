<?php

namespace App\VastAi\Services;

use DateTime;

class MonitorService
{
    private VastAiClient $client;
    private int $pollInterval;

    public function __construct(VastAiClient $client, int $pollInterval = 5)
    {
        $this->client = $client;
        $this->pollInterval = $pollInterval;
    }

    /**
     * Stream logs for an instance id. Normalizes lines, adds timestamps and yields them.
     * Returns array of lines when finished or throws exception on fatal error.
     */
    public function streamInstanceLogs(string $instanceId, int $timeoutSec = 0): array
    {
        $start = time();
        $collected = [];
        $since = null;

        while (true) {
            $now = time();
            if ($timeoutSec > 0 && ($now - $start) > $timeoutSec) {
                break;
            }

            $resp = $this->client->getInstanceLogs($instanceId, $since);
            if (isset($resp['error'])) {
                // push the error and continue after delay
                $line = $this->formatLine("[ERROR] {$resp['error']}");
                echo $line.PHP_EOL;
                $collected[] = $line;
                sleep($this->pollInterval);
                continue;
            }

            // resp may be raw text or array
            if (isset($resp['raw'])) {
                $lines = preg_split('/\r?\n/', $resp['raw']);
            } elseif (is_array($resp)) {
                $lines = $resp;
            } else {
                $lines = [(string)$resp];
            }

            foreach ($lines as $l) {
                $l = trim((string)$l);
                if ($l === '') continue;
                $timestamped = $this->formatLine($l);
                echo $timestamped.PHP_EOL;
                $collected[] = $timestamped;
            }

            // Update since to now to avoid refetching old logs if API supports it
            $since = time();

            // small sleep before next poll
            sleep($this->pollInterval);

            // Quick exit: if instance reports finished in logs, try to detect success marker
            foreach ($collected as $row) {
                if (stripos($row, 'VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY') !== false) {
                    return $collected;
                }
            }
        }

        return $collected;
    }

    private function formatLine(string $line): string
    {
        $dt = new DateTime();
        return '[' . $dt->format('Y-m-d H:i:s') . '] [LOG] ' . $line;
    }
}

