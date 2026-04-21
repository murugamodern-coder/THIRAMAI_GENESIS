import axios from 'axios';

export class PerplexityService {
  constructor(apiKey) {
    this.client = axios.create({
      baseURL: 'https://api.perplexity.ai',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json'
      }
    });
  }

  async search(query, depth = 3) {
    const { data } = await this.client.post('/chat/completions', {
      model: 'llama-3.1-sonar-large-128k-online',
      messages: [
        {
          role: 'system',
          content: `You are a research agent. Search depth: ${depth}/5.
                    Return structured findings with sources.
                    Format: { findings: string[], sources: string[], confidence: number }`
        },
        { role: 'user', content: query }
      ],
      return_citations: true,
      search_recency_filter: 'month'
    });
    return {
      content: data.choices[0].message.content,
      citations: data.citations || []
    };
  }
}
