#include <pthread.h>
#include <unistd.h>

static void *work(void *stay_alive) {
    if (stay_alive) {
        sleep(60);
    }
    return NULL;
}

// These threads never enter Python, so threading.active_count() cannot see them.
int start_thread(int stay_alive) {
    pthread_t thread;
    int status = pthread_create(&thread, NULL, work, stay_alive ? (void *)1 : NULL);
    if (status != 0) {
        return status;
    }
    return stay_alive ? pthread_detach(thread) : pthread_join(thread, NULL);
}
