import { ApiError } from './auth'

export function chatError(error: unknown, onSessionExpired: () => void) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      onSessionExpired()
      return ''
    }

    switch (error.code) {
      case 'RATE_LIMITED':
        return 'Trop de requêtes. Attends un instant avant de réessayer.'
      case 'DOCUMENT_NOT_READY':
      case 'NO_READY_DOCUMENTS':
        return 'Sélectionne au moins un PDF dont le statut est Prêt.'
      case 'SOURCES_CHANGED':
        return 'Les PDF ont changé pendant la réponse. Vérifie les sources et repose ta question.'
      case 'DOCUMENT_NOT_FOUND':
        return 'Ce PDF est indisponible. Actualise tes documents.'
      case 'CONVERSATION_NOT_FOUND':
        return 'Cette conversation a été supprimée ou est indisponible.'
      case 'LLM_UNAVAILABLE':
      case 'EMBEDDING_UNAVAILABLE':
      case 'INVALID_LLM_RESPONSE':
        return 'La réponse est temporairement indisponible. Tu peux reposer ta question.'
    }
  }
  return 'Impossible de terminer cette opération. Réessaie dans un instant.'
}
