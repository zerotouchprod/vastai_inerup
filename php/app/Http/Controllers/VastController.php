<?php

namespace App\VastAi\Http\Controllers;

use App\VastAi\Services\VastAiClient;

class VastController
{
    private VastAiClient $client;

    public function __construct()
    {
        $this->client = new VastAiClient();
    }

    public function search(array $filters = [])
    {
        return $this->client->searchOffers($filters);
    }

    public function create(array $payload)
    {
        return $this->client->createInstance($payload);
    }

    public function status(string $id)
    {
        return $this->client->getInstance($id);
    }
}

