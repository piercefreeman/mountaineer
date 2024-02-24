from tqdm import tqdm


def calculate_primes(up_to: int):
    def is_prime(n: int) -> bool:
        if n < 2:
            return False
        for i in range(2, int(n**0.5) + 1):
            if n % i == 0:
                return False
        return True

    return sum(is_prime(i) for i in tqdm(range(2, up_to + 1)))
