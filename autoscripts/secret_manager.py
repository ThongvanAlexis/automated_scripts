
def get_secret(secret_name: str) -> str:
    """
    Return the secret identified by `secret_name`.

    Secrets are expected to be provided by the execution environment.
    Raise an exception if the secret cannot be retrieved.
    """
    raise NotImplementedError("get_secret() must be implemented by the user")