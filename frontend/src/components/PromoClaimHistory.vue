<script setup>
import { onMounted, ref, watch } from 'vue'
import api from '../services/api'

const emit = defineEmits(['revoked'])

const claims = ref([])
const currentPage = ref(1)
const lastPage = ref(1)
const total = ref(0)
const statusFilter = ref('')
const loading = ref(false)
const errorMessage = ref('')
const revokingIds = ref(new Set())
const revokeErrors = ref({})

const statusOptions = [
  { value: '', label: 'All' },
  { value: 'applied', label: 'Applied' },
  { value: 'revoked', label: 'Revoked' },
]

async function fetchHistory(page = 1) {
  loading.value = true
  errorMessage.value = ''

  try {
    const { data } = await api.get('/promo/history', {
      params: {
        page,
        ...(statusFilter.value ? { status: statusFilter.value } : {}),
      },
    })

    claims.value = data.data
    currentPage.value = data.current_page
    lastPage.value = data.last_page
    total.value = data.total
  } catch (error) {
    errorMessage.value = error.response?.data?.message || 'Failed to load claim history.'
  } finally {
    loading.value = false
  }
}

function goToPage(page) {
  if (page < 1 || page > lastPage.value || page === currentPage.value || loading.value) return
  fetchHistory(page)
}

watch(statusFilter, () => fetchHistory(1))

// Called by the parent right after a successful claim so the new entry
// shows up immediately, without waiting on a refetch.
function prependClaim(claim) {
  if (currentPage.value !== 1) return
  if (statusFilter.value && statusFilter.value !== claim.status) return

  claims.value = [claim, ...claims.value]
  total.value += 1
}

defineExpose({ prependClaim })

async function revokeClaim(claim) {
  if (revokingIds.value.has(claim.id)) return
  if (!window.confirm(`Скасувати застосування промокоду на суму ${claim.amount}?`)) return

  revokingIds.value.add(claim.id)
  delete revokeErrors.value[claim.id]

  try {
    const { data } = await api.patch(`/promo/${claim.id}/revoke`)

    const index = claims.value.findIndex((c) => c.id === claim.id)
    if (index !== -1) {
      claims.value[index] = { ...claims.value[index], status: data.claim.status }
    }

    emit('revoked', { claim: data.claim, balance: data.balance })
  } catch (error) {
    revokeErrors.value[claim.id] = error.response?.data?.message || 'Failed to revoke this claim.'
  } finally {
    revokingIds.value.delete(claim.id)
  }
}

onMounted(() => fetchHistory())
</script>

<template>
  <section class="promo-history">
    <div class="promo-history__header">
      <h2 class="promo-history__title">Claim history</h2>
      <select v-model="statusFilter" class="promo-history__filter" :disabled="loading">
        <option v-for="option in statusOptions" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
    </div>

    <p v-if="loading" class="promo-history__hint">Loading…</p>
    <p v-else-if="errorMessage" class="promo-history__message promo-history__message--error">{{ errorMessage }}</p>
    <p v-else-if="claims.length === 0" class="promo-history__hint">No promo claims yet.</p>

    <table v-else class="promo-history__table">
      <thead>
        <tr>
          <th>Date</th>
          <th>Amount</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="claim in claims" :key="claim.id">
          <td>{{ new Date(claim.created_at).toLocaleString() }}</td>
          <td>+{{ claim.amount }}</td>
          <td>
            <span :class="['promo-history__status', `promo-history__status--${claim.status}`]">
              {{ claim.status }}
            </span>
          </td>
          <td>
            <div v-if="claim.status === 'applied'" class="promo-history__actions">
              <button
                type="button"
                class="promo-history__revoke"
                :disabled="revokingIds.has(claim.id)"
                @click="revokeClaim(claim)"
              >
                {{ revokingIds.has(claim.id) ? 'Скасування…' : 'Скасувати' }}
              </button>
              <p v-if="revokeErrors[claim.id]" class="promo-history__message promo-history__message--error">
                {{ revokeErrors[claim.id] }}
              </p>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="lastPage > 1" class="promo-history__pagination">
      <button type="button" :disabled="currentPage <= 1 || loading" @click="goToPage(currentPage - 1)">
        Prev
      </button>
      <span>Page {{ currentPage }} of {{ lastPage }} ({{ total }} total)</span>
      <button type="button" :disabled="currentPage >= lastPage || loading" @click="goToPage(currentPage + 1)">
        Next
      </button>
    </div>
  </section>
</template>

<style scoped>
.promo-history {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.promo-history__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.promo-history__title {
  margin: 0;
  font-size: 1.125rem;
  color: var(--text-h);
}

.promo-history__filter {
  padding: 0.375rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  background: var(--bg);
  color: var(--text-h);
  font: inherit;
}

.promo-history__hint {
  color: var(--text);
  font-size: 0.875rem;
}

.promo-history__message--error {
  color: #dc2626;
  font-size: 0.875rem;
}

.promo-history__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.promo-history__table th,
.promo-history__table td {
  text-align: left;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
}

.promo-history__table th {
  color: var(--text);
  font-weight: 600;
}

.promo-history__status {
  display: inline-block;
  padding: 0.125rem 0.5rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: capitalize;
}

.promo-history__status--applied {
  background: rgba(22, 163, 74, 0.12);
  color: #16a34a;
}

.promo-history__status--revoked {
  background: rgba(220, 38, 38, 0.12);
  color: #dc2626;
}

.promo-history__actions {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  align-items: flex-start;
}

.promo-history__revoke {
  padding: 0.25rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  background: var(--bg);
  color: #dc2626;
  font: inherit;
  font-size: 0.8125rem;
  cursor: pointer;
  white-space: nowrap;
}

.promo-history__revoke:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.promo-history__actions .promo-history__message--error {
  margin: 0;
  font-size: 0.75rem;
}

.promo-history__pagination {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.875rem;
  color: var(--text);
}

.promo-history__pagination button {
  padding: 0.25rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  background: var(--bg);
  color: var(--text-h);
  font: inherit;
  cursor: pointer;
}

.promo-history__pagination button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
