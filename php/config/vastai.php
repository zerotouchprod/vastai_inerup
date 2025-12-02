<?php

return [
    'api_key' => env('VAST_API_KEY', null),
    'api_url' => env('VAST_API_URL', 'https://api.vast.ai'),
    'default_preset' => env('DEFAULT_PRESET', 'balanced'),
];

