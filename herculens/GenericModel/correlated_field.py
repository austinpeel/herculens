# This module defines a generic pixelated model that can be used in conjunction with LightModel or MassModel's pixelated profiles.
# This is a forward model based on Gaussian processes, called a correlated field.
# The implementation is a wrapper around the NIFTy.re (a.k.a JIFTy) correlated field model.

__author__ = 'aymgal'

import numpy as np
import jax
import jax.numpy as jnp
from herculens.Util import jifty_util


__all__ = ['CorrelatedField']


class CorrelatedField(object):
    """Initialize the CorrelatedField class, based on the NIFTy.re correlated field model.
    
    For more details about the `prior_` arguments, please refer to 
    the NIFTy documentation. In particular, this documentation webpage gives
    a visual intuition of the different parameters:
    https://ift.pages.mpcdf.de/nifty/user/old_nifty_getting_started_4_CorrelatedFields.html

    Parameters
    ----------
    param_prefix : str
        The suffix to be added to the field parameters name.
    mass_or_light_model : object
        The mass or light model instance.
    offset_mean : float, optional
        The global additive offset applied to the field realizations, by default np.log(1e-2).
        NOTE: if `exponentiate` is True, this value should be the log-space of the chosen offset value.
    prior_offset_std : tuple, optional
        The The mean and scatter of the log-normal of the offset, by default (0.5, 1e-6).
    prior_loglogavgslope : tuple, optional
        The mean and scatter of the log-normal distribution for the average slope
         of the power-spectrum in log-log space, by default (-4., 0.5).
    prior_fluctuations : tuple, optional
        The mean and scatter of the log-normal distribution for the fluctuations, by default (1.5, 0.8).
    prior_flexibility : object, optional
        The mean and scatter of the log-normal distribution for the flexibility, by default None.
    prior_asperity : object, optional
        The mean and scatter of the log-normal distribution for the asperity, by default None.
    cropped_border_size : int, optional
        The field can optionally be evaluated on a larger grid size,
        and then cropped to return the model in direct space, by default 0.
        This is the number of pixels added on each size of the pixelated grid.
    prior_loglogavgslope_wl : tuple, optional
        The mean and scatter of the log-normal distribution for the average slope
         of the power-spectrum in log-log space along the spectral dimensions, by default (-2., 0.5).
    prior_fluctuations_wl : tuple, optional
        The mean and scatter of the log-normal distribution for the fluctuations along the spectral dimensions, by default (0.3, 0.8).
    prior_flexibility_wl : object, optional
        The mean and scatter of the log-normal distribution for the flexibility along the spectral dimensions, by default None.
    prior_asperity_wl : object, optional
        The mean and scatter of the log-normal distribution for the asperity along the spectral dimensions, by default None.
    num_bands : int, optional
        The number of spectral bands, by default 1.
    cropped_border_size_wl : int, optional
        The field can optionally be evaluated on more than the targeted spectral dimensions,
        and then cropped to return the model in direct space, by default 0.
        This is the number of pixels added on each size of the pixelated grid along the spectral dimensions.
    exponentiate : bool, optional
        Whether to return the exponential of the field, by default True. 
        For example, taking the exponential is useful to ensures non–negative values.

    Raises
    ------
    ValueError
        If the model does not have at least one Pixelated profile.
    ValueError
        If the number of pixels has not been set at creation of the LightModel or MassModel instance.
    """
    def __init__(
            self, 
            param_prefix, 
            mass_or_light_model, 

            # General parameters
            offset_mean=np.log(1e-2),
            prior_offset_std=(0.5, 1e-6),

            # Parameters along the spatial dimensions (`xy_dim`)
            prior_loglogavgslope=(-4., 0.5), 
            prior_fluctuations=(1.5, 0.8),
            prior_flexibility=None,
            prior_asperity=None,
            cropped_border_size=0,

            # Parameters along the spectral, or wavelength dimensions (`wl_dim`)
            num_bands=1,
            prior_loglogavgslope_wl=(-2., 0.5), 
            prior_fluctuations_wl=(0.3, 0.8),
            prior_flexibility_wl=None,
            prior_asperity_wl=None,
            cropped_border_size_wl=0,

            # Non-linearity
            exponentiate=True,
        ):
        # Check that the model is pixelated
        if not mass_or_light_model.has_pixels:
            raise ValueError("The provided LightModel or MassModel must contain "
                             "at least one Pixelated profile for proper use "
                             "with the CorrelatedField model.")
        
        # retrieve the number of pixels from the LightModel instance
        # NOTE: the following is to support both when the CorrelatedField is instantiated
        # before or after the LightModel or a MassModel is passed a LensImage instance.
        # TODO: simplify this when pixelated profiles treatment is improved in LensImage.
        try:
            self._num_pix, self._num_pix_y = mass_or_light_model.pixel_grid.num_pixel_axes
        except AttributeError:
            self._num_pix = mass_or_light_model.pixel_grid_settings.get('num_pixels', None)
        else:
            if self._num_pix != self._num_pix_y:
                raise NotImplementedError("Only square pixel grids are supported for now.")
        # Pack the prior choices
        if any([p is None for p in [offset_mean, prior_offset_std, prior_loglogavgslope, prior_fluctuations]]):
            raise ValueError("Field parameters and priors `offset_mean`, `prior_offset_std`, `prior_loglogavgslope`, `prior_fluctuations` are mandatory.")
        self._kw_amplitude_offset = {
            'offset_mean': offset_mean,
            'offset_std': prior_offset_std,
        }
        self._kw_fluctuations = {
            # Amplitude of field fluctuations
            'fluctuations': prior_fluctuations,

            # Exponent of power law power spectrum component
            'loglogavgslope': prior_loglogavgslope,

            # Extra degrees of freedom
            # NOTE: I did not test much these two in a strong lensing context
            'flexibility': prior_flexibility, 
            'asperity': prior_asperity,
        }
        if num_bands > 1:
            self._kw_fluctuations_wl = {
                'fluctuations': prior_fluctuations_wl,
                'loglogavgslope': prior_loglogavgslope_wl,
                'flexibility': prior_flexibility_wl,
                'asperity': prior_asperity_wl,
            }
        else:
            self._kw_fluctuations_wl = None

        # Setup the correlated field model
        self._param_prefix = param_prefix
        self._key_xy = 'xy_dim'
        self._key_wl = 'wl_dim'
        self._cfm, self._jft_model, self._num_pix_tot, self._num_wl_tot = jifty_util.prepare_correlated_field(
            self._param_prefix,
            self._num_pix,
            cropped_border_size,
            kwargs_amplitude=self._kw_amplitude_offset,
            kwargs_fluctuations=self._kw_fluctuations,
            num_pix_wl=num_bands, 
            border_wl=cropped_border_size_wl if num_bands > 1 else 0,
            kwargs_fluctuations_wl=self._kw_fluctuations_wl,
            non_linearity='exp' if exponentiate else 'none',
            param_key_xy=self._key_xy,
            param_key_wl=self._key_wl,
        )

    def __call__(self, params):
        """Evaluate the model at the given parameters.
        The parameters keys are:
        - '{param_prefix}_field_xi': the field fluctuations
        - '{param_prefix}_field_zeromode': the zero mode of the field
        - '{param_prefix}_field_{dim_type}_dim_fluctuations': the field fluctuations (along the spatial dimensions)
        - '{param_prefix}_field_{dim_type}_dim_loglogavgslope': the log-log average slope of the power-spectrum (along the spatial dimensions)
        - '{param_prefix}_field_{dim_type}_dim_flexibility': the flexibility (along the spatial dimensions)
        - '{param_prefix}_field_{dim_type}_dim_asperity': the asperity (along the spatial dimensions)
        where `dim_type` is either 'xy' (spatial dimensions) or 'wl' (wavelength dimension).

        Parameters
        ----------
        params : Pytree
            Parameters values as a Pytree (e.g. dict).

        Returns
        -------
        jnp.Array
            Field model (in direct space), as 2d array.
        """
        return self._jft_model(params)[self._param_prefix]
    
    def model(self, params):
        """Just a handy alias"""
        return self(params)

    def numpyro_sample_pixels(self):
        """Defines the numpyro model to be used in a Pixelated (light or mass) profile.
        
        This method is only meant to be called within a numpyro model definition,
        as it defines the prior distribution (which are all standard normally distributed) for the field parameters.

        Returns
        -------
        jnp.Array
            Field model (in direct space), as 2d array.
        """
        if self._num_wl_tot == 1:
            return self._numpyro_sample_pixels_2d()
        else:
            return self._numpyro_sample_pixels_3d()
        
    def _numpyro_sample_pixels_2d(self):
        # TODO: reduce code duplication
        # imports here to prevent the need for numpyro to be installed
        # if the CorrelatedField class is used in a non-numpyro context.
        import numpyro
        from numpyro.distributions import Normal, Independent
        # Base field parameters
        params = {
            f'{self._param_prefix}_field_xi': numpyro.sample(
                f'{self._param_prefix}_field_xi', 
                Independent(Normal(
                    jnp.zeros((self._num_pix_tot, self._num_pix_tot)), 
                    jnp.ones((self._num_pix_tot, self._num_pix_tot))
                ), reinterpreted_batch_ndims=2)
            ),
            f'{self._param_prefix}_field_zeromode': numpyro.sample(
                f'{self._param_prefix}_field_zeromode', 
                Normal(0., 1.),
            ),
            f'{self._param_prefix}_field_{self._key_xy}_fluctuations': numpyro.sample(
                f'{self._param_prefix}_field_{self._key_xy}_fluctuations', 
                Normal(0., 1.),
            ),
            f'{self._param_prefix}_field_{self._key_xy}_loglogavgslope': numpyro.sample(
                f'{self._param_prefix}_field_{self._key_xy}_loglogavgslope', 
                Normal(0., 1.),
            ),
        }
        # Additional optional field parameters
        if self._kw_fluctuations['flexibility'] is not None:
            params[f'{self._param_prefix}_field_{self._key_xy}_flexibility'] = numpyro.sample(
                f'{self._param_prefix}_field_{self._key_xy}_flexibility', 
                Normal(0., 1.),
            )
        if self._kw_fluctuations['asperity'] is not None:
            params[f'{self._param_prefix}_field_{self._key_xy}_asperity'] = numpyro.sample(
                f'{self._param_prefix}_field_{self._key_xy}_asperity', 
                Normal(0., 1.),
            )
        return self(params)
    
    def _numpyro_sample_pixels_3d(self):
        # TODO: reduce code duplication
        # imports here to prevent the need for numpyro to be installed
        # if the CorrelatedField class is used in a non-numpyro context.
        import numpyro
        from numpyro.distributions import Normal, Independent
        # Base field parameters
        params = {
            f'{self._param_prefix}_field_zeromode': numpyro.sample(
                f'{self._param_prefix}_field_zeromode', 
                Normal(0., 1.),
            ),
            f'{self._param_prefix}_field_xi': numpyro.sample(
                f'{self._param_prefix}_field_xi', 
                Independent(Normal(
                    jnp.zeros((self._num_wl_tot, self._num_pix_tot, self._num_pix_tot)), 
                    jnp.ones((self._num_wl_tot, self._num_pix_tot, self._num_pix_tot))
                ), reinterpreted_batch_ndims=3)
            ),
            f'{self._param_prefix}_field_{self._key_xy}_fluctuations': numpyro.sample(
                f'{self._param_prefix}_field_{self._key_xy}_fluctuations', 
                Normal(0., 1.),
            ),
            f'{self._param_prefix}_field_{self._key_xy}_loglogavgslope': numpyro.sample(
                f'{self._param_prefix}_field_{self._key_xy}_loglogavgslope', 
                Normal(0., 1.),
            ),
            f'{self._param_prefix}_field_{self._key_wl}_fluctuations': numpyro.sample(
                f'{self._param_prefix}_field_{self._key_wl}_fluctuations', 
                Normal(0., 1.),
            ),
            f'{self._param_prefix}_field_{self._key_wl}_loglogavgslope': numpyro.sample(
                f'{self._param_prefix}_field_{self._key_wl}_loglogavgslope', 
                Normal(0., 1.),
            ),
        }
        # Additional optional field parameters
        if self._kw_fluctuations['flexibility'] is not None:
            params[f'{self._param_prefix}_field_{self._key_xy}_flexibility'] = numpyro.sample(
                f'{self._param_prefix}_field_{self._key_xy}_flexibility', 
                Normal(0., 1.),
            )
        if self._kw_fluctuations['asperity'] is not None:
            params[f'{self._param_prefix}_field_{self._key_xy}_asperity'] = numpyro.sample(
                f'{self._param_prefix}_field_{self._key_xy}_asperity', 
                Normal(0., 1.),
            )
        if self._kw_fluctuations_wl['flexibility'] is not None:
            params[f'{self._param_prefix}_field_{self._key_wl}_flexibility'] = numpyro.sample(
                f'{self._param_prefix}_field_{self._key_wl}_flexibility', 
                Normal(0., 1.),
            )
        if self._kw_fluctuations_wl['asperity'] is not None:
            params[f'{self._param_prefix}_field_{self._key_wl}_asperity'] = numpyro.sample(
                f'{self._param_prefix}_field_{self._key_wl}_asperity', 
                Normal(0., 1.),
            )
        return self(params)
    
    def draw_realizations_from_prior(self, prng_key, num_samples=10, return_parameters=False):
        """Draw a random field realization from the prior distribution.

        Returns
        -------
        jnp.Array
            Field model (in direct space), as 2d array.
        """
        # imports here to prevent the need for numpyro to be installed
        # if the CorrelatedField class is used in a non-numpyro context.
        from numpyro.infer import Predictive
        def model():
            """This just to define a callable the 'numpyro way'"""
            self.numpyro_sample_pixels()
        # draw sample from the latent space (i.e. standard normal samples)
        prior_samples = Predictive(model, num_samples=num_samples)(prng_key)
        # evaluate the model at the prior samples
        model_samples = jax.vmap(self)(prior_samples)
        # if there is only one sample, remove the first dimension
        if num_samples == 1:
            model_samples = jnp.squeeze(model_samples, axis=0)
        if return_parameters:
            return model_samples, prior_samples
        return model_samples
    
    @property
    def correlated_field_maker(self):
        return self._cfm
    
    @property
    def num_pix_field(self):
        return self._num_pix_tot
    
    @property
    def num_pix(self):
        return self._num_pix
    
    @property
    def num_wl_field(self):
        return self._num_wl_tot
    
    @property
    def num_wl(self):
        return self._num_pix_wl
