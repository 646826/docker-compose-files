import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 2,
  duration: '10s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    checks: ['rate>0.99'],
  },
};

export default function () {
  const response = http.get(__ENV.TARGET_URL || 'http://whoami');

  check(response, {
    'status is 200': (result) => result.status === 200,
  });

  sleep(1);
}
