import axios from 'axios';

export class QuiverService {
  constructor(apiKey) {
    this.client = axios.create({
      baseURL: 'https://api.quiverquant.com/beta',
      headers: { Authorization: `Token ${apiKey}` }
    });
  }

  async getCongressTrading(ticker) {
    const { data } = await this.client.get(`/historical/congresstrading/${ticker}`);
    return data.slice(0, 10); // last 10 trades
  }

  async getSentiment(ticker) {
    const { data } = await this.client.get(`/historical/wallstreetbets/${ticker}`);
    return data.slice(0, 5);
  }

  async getInsiderTrading(ticker) {
    const { data } = await this.client.get(`/historical/insiders/${ticker}`);
    return data.slice(0, 5);
  }
}
