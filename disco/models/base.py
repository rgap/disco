import torch as th


class BaseModel:
    """Base class for forward models used in the DISCO framework.

    .. note::
        Unlike Gym, this is *not* an environment. Effectively, this means
        that the model does not hold the current system state. This is useful to
        compute several system trajectories in parallel and vectorize the code.

        Furthermore, as we are interested in uncertain dynamics, models should
        hold a probability distribution over their uncertain parameters. This
        means each derived model must support the BaseModel functions to assign
        and sample from a distribution over some or all of its parameters.
    """

    def __init__(
        self, dt=0.05, uncertain_params=None, params_dist=None,
    ):
        """Constructor for BaseModel.

        :param dt: Duration of each discrete update in s. (default: 0.05)
        :type dt: float
        :param uncertain_params: A list containing the uncertain parameters of
            the forward model. Is used as keys for assigning sampled parameters
            from the `params_dist` function.
        :type uncertain_params:
        :param params_dist: A distribution to sample parameters for the forward
            model.
        :type params_dist: torch.distributions.distribution.Distribution
        """
        assert dt > 0, "Delta t must be greater than zero."
        self.__dt = dt

        assert (uncertain_params is None and params_dist is None) or (
            uncertain_params is not None and params_dist is not None
        ), "Need to specify uncertain parameters and their distribution."
        self.__params_keys = uncertain_params
        self.params_dist = params_dist

    @property
    def dt(self):
        """Returns the discrete timestep duration."""
        return self.__dt

    @property
    def uncertain_params(self):
        """Returns the list of uncertain parameters."""
        return self.__params_keys

    @property
    def params_dist(self):
        """Returns the distribution over uncertain parameters."""
        return self.__params_dist

    @params_dist.setter
    def params_dist(self, dist):
        if dist is not None:
            assert len(dist.mean) == len(
                self.__params_keys
            ), "Number of uncertain parameters must match their distribution."
        self.__params_dist = dist

    @property
    def action_space(self):
        """Returns a Space object."""
        raise NotImplementedError

    @property
    def observation_space(self):
        """Returns a Space object."""
        raise NotImplementedError

    def step(self, states, actions, sampled_params=None):
        """Receives tensors of current states and actions and computes the
        states for the subsequent timestep. If sampled parameters are provided,
        these must be used, otherwise revert to mode of distribution over the
        uncertain parameters.

        Must be bounded by observation and action spaces.

        :param states: A tensor containing the current states of one or multiple
            trajectories.
        :type states: th.Tensor
        :param actions: A tensor containing the next planned actions of one or
            multiple trajectories.
        :type actions: th.Tensor
        :param sampled_params: A tensor containing samples for the uncertain
            system parameters. Note that the number of samples must be either 1
            or the number of trajectories. If 1, a single sample is used for all
            trajectories, otherwise use one sample per trajectory.
        :type sampled_params: dict
        :returns: A tensor with the next states of one or multiple trajectories.
        :rtype: th.Tensor
        """
        raise NotImplementedError

    def rejection_sampling(
        self, num_samples, x_min=-float("inf"), x_max=float("inf")
    ):
        """Samples model parameters using Rejection Sampling.

        :param num_samples: A integer with the number of output samples.
        :type num_samples: int
        :param x_min: Minimum value accepted for each sample. Same for all
            dimensions.
        :type x_min: float
        :param x_max: Maximum value accepted for each sample. Same for all
            dimensions.
        :type x_max: float
        :returns: Samples in a  2-D tensor of dimensions `n_samples` x
        `uncertain_parameters`.
        :rtype: th.Tensor
        """
        n_samples = num_samples
        dim_params = len(self.__params_keys)

        n_accepts = 0
        n_attempts = 0
        # Keeps generating numbers until we achieve the desired n
        samples = th.FloatTensor()  # output list of accepted samples
        while n_accepts < n_samples:
            # valid_samples replaces samples outside boundaries with 'nan'
            valid_samples = self.params_dist.sample([n_samples - n_accepts])
            valid_samples = valid_samples.where(
                x_min < valid_samples, th.as_tensor(float("nan"))
            )
            valid_samples = valid_samples.where(
                x_max > valid_samples, th.as_tensor(float("nan"))
            )
            # adds elements which are not nan to samples
            if dim_params == 1:
                samples = th.cat(
                    (samples, valid_samples[~th.isnan(valid_samples)]), 0
                )
                n_accepts = samples.numel()
            else:
                samples = th.cat(
                    (
                        samples,
                        valid_samples[~th.isnan(valid_samples.sum(dim=1))],
                    ),
                    0,
                )
                n_accepts = samples.numel() / dim_params
            n_attempts = n_attempts + 1

        return samples.reshape([n_samples] + [dim_params]), n_attempts

    def sample_params(
        self, num_samples, x_min=-float("inf"), x_max=float("inf")
    ):
        """Samples parameters for the forward model.

        :param num_samples: a list with the length of the parameter vector.
        Must be either [1] for a single set of parameters per time step for all
        trajectories, or [n_samples] for individual set o parameters for each
        trajectory at each time step (default: [1]).
        :param x_min: minimum accepted values for sampled parameters, same for
            all dimensions.
        :param x_max: maximum accepted values for sampled parameters, same for
            all dimensions.
        :returns: A dictionary of tensors containing the sampled parameters.
        :rtype: dict
        """
        assert (
            self.params_dist is not None
        ), "No sampling distribution specified"

        assert num_samples > 0, "Need at least one sample."

        samples, _ = self.rejection_sampling(
            num_samples, x_min=x_min, x_max=x_max
        )
        return {
            key: samples[:, idx].reshape(-1, 1)
            for (idx, key) in enumerate(self.__params_keys)
        }

    def to_params_dict(self, params):
        return {
            key: params[:, idx].reshape(-1, 1)
            for (idx, key) in enumerate(self.__params_keys)
        }
