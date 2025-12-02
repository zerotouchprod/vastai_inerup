<?php

namespace App\VastAi\Services;

use GuzzleHttp\Client;
use GuzzleHttp\Exception\GuzzleException;

class VastAiClient
{
    private Client $http;
    private string $apiKey;
    private string $baseUrl;

    public function __construct(?string $apiKey = null, ?string $baseUrl = null)
    {
        $this->apiKey = $apiKey ?? getenv('VAST_API_KEY');
        $this->baseUrl = rtrim($baseUrl ?? getenv('VAST_API_URL') ?? 'https://api.vast.ai', '/');
        $headers = [
            'Accept' => 'application/json',
        ];
        if ($this->apiKey) {
            $headers['Authorization'] = "Bearer {$this->apiKey}";
        }
        $this->http = new Client([
            'base_uri' => $this->baseUrl,
            'timeout' => 30,
            'headers' => $headers,
        ]);
    }

    public function searchOffers(array $filters = []): array
    {
        // Build query params from filters
        $params = ['json' => array_merge(['q' => ''], $filters)];

        try {
            $resp = $this->http->post('/public/list-offers', $params);
            $data = json_decode((string)$resp->getBody(), true);
            return $data ?? [];
        } catch (GuzzleException $e) {
            return ['error' => $e->getMessage()];
        }
    }

    public function createInstance(array $payload): array
    {
        try {
            $resp = $this->http->post('/public/instances/create', ['json' => $payload]);
            $data = json_decode((string)$resp->getBody(), true);
            return $data ?? [];
        } catch (GuzzleException $e) {
            return ['error' => $e->getMessage()];
        }
    }

    public function getInstance(string $id): array
    {
        try {
            $resp = $this->http->get("/public/instances/{$id}");
            $data = json_decode((string)$resp->getBody(), true);
            return $data ?? [];
        } catch (GuzzleException $e) {
            return ['error' => $e->getMessage()];
        }
    }

    /**
     * Generic request helper with safe JSON decode
     */
    private function request(string $method, string $path, array $options = []): array
    {
        try {
            $resp = $this->http->request($method, $path, $options);
            $body = (string)$resp->getBody();
            $data = json_decode($body, true);
            if (json_last_error() !== JSON_ERROR_NONE) {
                // return raw body on decode failure
                return ['raw' => $body];
            }
            return $data ?? [];
        } catch (GuzzleException $e) {
            return ['error' => $e->getMessage()];
        }
    }

    /**
     * Attempts to fetch instance logs. Vast API shapes differ; try a couple of endpoints
     * Returns array of log lines or ['error'=>...] on failure.
     */
    public function getInstanceLogs(string $instanceId, ?int $since = null): array
    {
        // Try endpoint 1: /public/instances/{id}/logs
        $path = "/public/instances/{$instanceId}/logs";
        $params = [];
        if ($since !== null) {
            $params['query'] = ['since' => $since];
        }

        $resp = $this->request('GET', $path, $params);
        if (isset($resp['error'])) {
            // Fallback: fetch instance details and look for logs field
            $inst = $this->getInstance($instanceId);
            if (isset($inst['error'])) {
                return ['error' => "Logs fetch failed: {$resp['error']}; instance fetch failed: {$inst['error']}" ];
            }
            if (isset($inst['logs']) && is_array($inst['logs'])) {
                return $inst['logs'];
            }
            // Final fallback: try /public/instances/logs?instance={id}
            $resp2 = $this->request('GET', '/public/instances/logs', ['query' => ['instance' => $instanceId]]);
            if (isset($resp2['error'])) {
                return ['error' => "Logs unavailable: {$resp['error']} / {$resp2['error']}" ];
            }
            // If resp2 is array of lines or structure, attempt to normalize
            if (is_array($resp2)) {
                return $resp2;
            }
            return ['error' => 'Logs endpoint returned unexpected data'];
        }

        return $resp;
    }
}
