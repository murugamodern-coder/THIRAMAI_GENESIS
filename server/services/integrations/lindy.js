import axios from 'axios';

export class LindyService {
  constructor(apiKey) {
    this.client = axios.create({
      baseURL: 'https://api.lindy.ai/v1',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' }
    });
  }

  async getTasks() {
    try {
      const { data } = await this.client.get('/tasks?status=pending&limit=20');
      return { ok: true, tasks: data.tasks || [] };
    } catch (err) {
      return { ok: false, error: err.message, tasks: [] };
    }
  }

  async getWorkflows() {
    try {
      const { data } = await this.client.get('/workflows?active=true');
      return { ok: true, workflows: data.workflows || [] };
    } catch (err) {
      return { ok: false, error: err.message, workflows: [] };
    }
  }
}
