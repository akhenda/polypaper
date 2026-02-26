const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3001';

export async function fetchDashboard() {
  const res = await fetch(`${API_URL}/api/v1/dashboard`);
  if (!res.ok) throw new Error('Failed to fetch dashboard');
  return res.json();
}

export async function fetchMarkets() {
  const res = await fetch(`${API_URL}/api/v1/markets`);
  if (!res.ok) throw new Error('Failed to fetch markets');
  return res.json();
}

export async function fetchPositions(accountId?: string) {
  const url = accountId 
    ? `${API_URL}/api/v1/positions?accountId=${accountId}`
    : `${API_URL}/api/v1/positions?open=true`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('Failed to fetch positions');
  return res.json();
}

export async function fetchOrders(accountId?: string) {
  const url = accountId 
    ? `${API_URL}/api/v1/orders?accountId=${accountId}`
    : `${API_URL}/api/v1/orders`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('Failed to fetch orders');
  return res.json();
}
