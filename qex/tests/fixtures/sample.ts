interface User {
  id: number;
  name: string;
  email: string;
}

export class AuthService {
  private token: string | null = null;

  async login(username: string, password: string): Promise<boolean> {
    // Authenticate with the API
    const response = await fetch('/api/auth', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
    if (response.ok) {
      this.token = await response.text();
      return true;
    }
    return false;
  }

  getToken(): string | null {
    return this.token;
  }
}

export async function fetchUser(id: number): Promise<User> {
  const response = await fetch(`/api/users/${id}`);
  return response.json();
}

export function validateEmail(email: string): boolean {
  const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return re.test(email);
}
